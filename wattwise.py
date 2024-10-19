import datetime

import appdaemon.plugins.hass.hassapi as hass
import numpy as np
import pulp
import pytz
import requests


class WattWise(hass.Hass):
    """
    WattWise is an AppDaemon application for Home Assistant that optimizes battery usage
    based on consumption forecasts, solar production forecasts, and energy price forecasts.
    It schedules charging and discharging actions to minimize energy costs and maximize
    battery efficiency.

    Attributes:
        BATTERY_CAPACITY (float): The total capacity of the battery in kWh.
        BATTERY_EFFICIENCY (float): The efficiency of the battery (0 < efficiency <= 1).
        CHARGE_RATE_MAX (float): The maximum charging rate in kW.
        DISCHARGE_RATE_MAX (float): The maximum discharging rate in kW.
        TIME_HORIZON (int): The optimization time horizon in hours.
        FEED_IN_TARIFF (float): The tariff for feeding energy back to the grid in ct/kWh.
        CONSUMPION_SENSOR (str): Entity ID for the house consumption sensor.
        SOLAR_FORECAST_SENSOR_TODAY (str): Entity ID for today's solar forecast sensor.
        SOLAR_FORECAST_SENSOR_TOMORROW (str): Entity ID for tomorrow's solar forecast sensor.
        PRICE_FORECAST_SENSOR (str): Entity ID for the energy price forecast sensor.
        BATTERY_SOC_SENSOR (str): Entity ID for the battery state of charge sensor.
        BATTERY_CHARGER_SWITCH (str): Entity ID for the battery charger switch.
        BATTERY_DISCHARGER_SWITCH (str): Entity ID for the battery discharger switch.
        ha_url (str): URL of the Home Assistant instance.
        token (str): Authentication token for Home Assistant API.
        charging_from_grid (bool): Current state of charging from the grid.
        discharging_to_house (bool): Current state of discharging to the house.
    """

    def initialize(self):
        """
        Initializes the WattWise AppDaemon application.

        This method sets up the initial configuration, schedules the hourly optimization
        process, and listens for manual optimization triggers. It fetches initial states
        of charger and discharger switches to track current charging and discharging statuses.

        Raises:
            ValueError: If Home Assistant URL or token is not provided in app configuration.
        """
        # Constants for Static Parameters
        self.BATTERY_CAPACITY = 11.2  # kWh
        self.BATTERY_EFFICIENCY = 0.9
        self.CHARGE_RATE_MAX = 6  # kW
        self.DISCHARGE_RATE_MAX = 6  # kW
        self.TIME_HORIZON = 24  # hours
        self.FEED_IN_TARIFF = 7  # ct/kWh

        # Your Entity IDs
        self.CONSUMPTION_SENSOR = "sensor.s10x_house_consumption"
        self.SOLAR_FORECAST_SENSOR_TODAY = "sensor.solcast_pv_forecast_prognose_heute"
        self.SOLAR_FORECAST_SENSOR_TOMORROW = (
            "sensor.solcast_pv_forecast_prognose_morgen"
        )
        self.PRICE_FORECAST_SENSOR = "sensor.tibber_prices"
        self.BATTERY_SOC_SENSOR = "sensor.s10x_state_of_charge"  # SoC in percentage

        # WattWise's Helper Switches in Home Assistant. You can change these to existing switches you may have as well.
        self.BATTERY_CHARGER_SWITCH = "switch.wattwise_battery_charger"
        self.BATTERY_DISCHARGER_SWITCH = (
            "switch.wattwise_battery_discharger"  # Added discharger switch
        )

        # Get Home Assistant URL and token from app args
        self.ha_url = self.args.get("ha_url")
        self.token = self.args.get("token")

        if not self.ha_url or not self.token:
            self.error(
                "Home Assistant URL and token must be provided in app configuration."
            )
            return

        # Initialize state tracking variables
        self.charging_from_grid = False
        self.discharging_to_house = False

        # Fetch and set initial states from Home Assistant
        self.set_initial_states()

        # Schedule the optimization to run hourly at the top of the hour
        now = self.datetime()
        next_run = now.replace(minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += datetime.timedelta(hours=1)
        self.run_hourly(self.optimize_battery, next_run)
        self.log(f"Scheduled hourly optimization starting at {next_run}.")

        # Listen for a custom event to trigger optimization manually
        self.listen_event(self.manual_trigger, event="MANUAL_BATTERY_OPTIMIZATION")
        self.log(
            "Listening for manual optimization trigger event 'MANUAL_BATTERY_OPTIMIZATION'."
        )

    def set_initial_states(self):
        """
        Fetches and sets the initial states of the charger and discharger switches.

        This method retrieves the current state of the battery charger and discharger
        switches from Home Assistant and initializes the tracking variables
        `charging_from_grid` and `discharging_to_house` accordingly.
        """
        charger_state = self.get_state(self.BATTERY_CHARGER_SWITCH)
        discharger_state = self.get_state(self.BATTERY_DISCHARGER_SWITCH)

        if charger_state is not None:
            self.charging_from_grid = charger_state.lower() == "on"
            self.log(f"Initial charging_from_grid state: {self.charging_from_grid}")

        if discharger_state is not None:
            self.discharging_to_house = discharger_state.lower() == "on"
            self.log(f"Initial discharging_to_house state: {self.discharging_to_house}")

    def manual_trigger(self, event_name, data, kwargs):
        """
        Handles manual optimization triggers.

        This method is called when the custom event `MANUAL_BATTERY_OPTIMIZATION` is fired.
        It initiates the battery optimization process.

        Args:
            event_name (str): The name of the event.
            data (dict): The event data.
            kwargs (dict): Additional keyword arguments.
        """
        self.log("Manual optimization trigger received.")
        self.optimize_battery({})

    def optimize_battery(self, kwargs):
        """
        Executes the battery optimization process.

        This method retrieves the current state of charge, fetches forecasts for
        consumption, solar production, and energy prices, formulates and solves
        an optimization problem to determine the optimal charging and discharging
        schedule, updates forecast sensors, and schedules charging/discharging actions.

        Args:
            kwargs (dict): Additional keyword arguments.

        Returns:
            None

        Raises:
            RuntimeError: If the optimization problem does not find an optimal solution.
        """
        self.log("Starting battery optimization process.")

        # Get initial State of Charge (SoC) in percentage
        SoC_percentage_str = self.get_state(self.BATTERY_SOC_SENSOR)
        if SoC_percentage_str is None:
            self.error(
                f"Could not retrieve state of {self.BATTERY_SOC_SENSOR}. Aborting optimization."
            )
            return

        # Convert SoC from percentage to kWh
        SoC_percentage = float(SoC_percentage_str)
        SoC_0 = (SoC_percentage / 100) * self.BATTERY_CAPACITY
        self.log(
            f"Initial SoC: {SoC_0:.2f} kWh ({SoC_percentage}% of {self.BATTERY_CAPACITY} kWh)"
        )

        T = self.TIME_HORIZON

        # Get forecasts
        C_t = self.get_consumption_forecast(T)
        if C_t is None:
            self.error(
                "Consumption forecast data is unavailable. Aborting optimization."
            )
            return

        S_t = self.get_solar_production_forecast(T)
        if S_t is None:
            self.error(
                "Solar production forecast data is unavailable. Aborting optimization."
            )
            return

        P_t = self.get_energy_price_forecast(T)
        if P_t is None:
            self.error(
                "Energy price forecast data is unavailable. Aborting optimization."
            )
            return

        # Log the forecasts per hour for debugging
        self.log("Forecasts per hour:")
        now = self.datetime()  # Use AppDaemon's time-aware datetime
        for t in range(T):
            forecast_time = now + datetime.timedelta(hours=t)
            hour = forecast_time.hour
            self.log(
                f"Hour {hour:02d}: "
                f"Consumption = {C_t[t]:.2f} kW, "
                f"Solar = {S_t[t]:.2f} kW, "
                f"Price = {P_t[t]:.2f} ct/kWh"
            )

        # Initialize the optimization problem
        prob = pulp.LpProblem("Battery_Optimization", pulp.LpMinimize)
        self.log("Optimization problem initialized.")

        # Decision variables
        G = pulp.LpVariable.dicts("Grid_Import", (t for t in range(T)), lowBound=0)
        Ch_solar = pulp.LpVariable.dicts(
            "Battery_Charge_Solar", (t for t in range(T)), lowBound=0
        )
        Ch_grid = pulp.LpVariable.dicts(
            "Battery_Charge_Grid", (t for t in range(T)), lowBound=0
        )
        Dch = pulp.LpVariable.dicts(
            "Battery_Discharge", (t for t in range(T)), lowBound=0
        )
        SoC = pulp.LpVariable.dicts(
            "SoC", (t for t in range(T + 1)), lowBound=0, upBound=self.BATTERY_CAPACITY
        )
        E = pulp.LpVariable.dicts("Grid_Export", (t for t in range(T)), lowBound=0)
        Surplus_solar = pulp.LpVariable.dicts(
            "Surplus_Solar", (t for t in range(T)), lowBound=0
        )
        FullCharge = pulp.LpVariable.dicts(
            "FullCharge", (t for t in range(T)), cat="Binary"
        )  # Binary variables
        self.log("Decision variables created.")

        # Objective function: Minimize the total cost of grid imports and grid charging, minus value of final SoC
        P_end = np.mean(P_t)
        prob += (
            pulp.lpSum([P_t[t] * G[t] - self.FEED_IN_TARIFF * E[t] for t in range(T)])
            - P_end * SoC[T]
        )
        self.log(
            "Objective function set to minimize total cost minus value of final SoC."
        )

        # Initial SoC
        prob += SoC[0] == SoC_0
        self.log("Initial SoC constraint added.")

        M = self.BATTERY_CAPACITY * 2  # Big M value

        for t in range(T):
            # Energy balance with corrected battery efficiency
            prob += (
                (
                    S_t[t] + G[t] + Dch[t] * self.BATTERY_EFFICIENCY
                    == C_t[t] + Ch_solar[t] + Ch_grid[t] + E[t]
                ),
                f"Energy_Balance_{t}",
            )

            # SoC update with corrected battery efficiency
            prob += (
                SoC[t + 1]
                == SoC[t]
                + (Ch_solar[t] + Ch_grid[t]) * self.BATTERY_EFFICIENCY
                - Dch[t],
                f"SoC_Update_{t}",
            )

            # Battery capacity constraints
            prob += SoC[t + 1] >= 0, f"SoC_Min_{t}"
            prob += SoC[t + 1] <= self.BATTERY_CAPACITY, f"SoC_Max_{t}"

            # Charging limits
            prob += (
                Ch_solar[t] + Ch_grid[t] <= self.CHARGE_RATE_MAX,
                f"Charge_Rate_Limit_{t}",
            )
            prob += Ch_solar[t] <= self.CHARGE_RATE_MAX, f"Solar_Charge_Rate_Limit_{t}"
            prob += (
                Ch_solar[t] <= S_t[t],
                f"Charge_Solar_Limit_Actual_Solar_{t}",
            )  # Added constraint
            prob += Ch_grid[t] <= self.CHARGE_RATE_MAX, f"Grid_Charge_Rate_Limit_{t}"

            # Discharging limits
            prob += Dch[t] <= self.DISCHARGE_RATE_MAX, f"Discharge_Rate_Limit_{t}"

            # Surplus solar constraints
            prob += Surplus_solar[t] >= S_t[t] - C_t[t], f"Surplus_Solar_Definition_{t}"
            prob += Surplus_solar[t] >= 0, f"Surplus_Solar_NonNegative_{t}"
            prob += Ch_solar[t] <= Surplus_solar[t], f"Solar_Charging_Limit_{t}"

            # Charging from grid cannot exceed grid import
            prob += Ch_grid[t] <= G[t], f"Grid_Charging_Limit_{t}"

            # Grid export is non-negative
            prob += E[t] >= 0, f"Grid_Export_NonNegative_{t}"

            # Linking FullCharge[t] with SoC[t+1]
            prob += (
                SoC[t + 1] >= self.BATTERY_CAPACITY - (1 - FullCharge[t]) * M,
                f"SoC_FullCharge_Link_{t}",
            )

            # Enforcing E[t] based on FullCharge[t]
            prob += E[t] <= FullCharge[t] * M, f"Export_Only_When_Full_{t}"

        self.log("Constraints added to the optimization problem.")

        # Solve the problem using a solver that supports MILP
        self.log("Starting the solver.")
        solver = pulp.GLPK_CMD(msg=1)  # Removed invalid options
        prob.solve(solver)
        self.log(f"Solver status: {pulp.LpStatus[prob.status]}")

        # Check if an optimal solution was found
        if pulp.LpStatus[prob.status] != "Optimal":
            self.error("No optimal solution found for battery optimization.")
            return

        # Extract the optimized charging schedule
        charging_schedule = []
        now = self.datetime()  # Use time-aware datetime
        for t in range(T):
            charge_solar = Ch_solar[t].varValue
            charge_grid = Ch_grid[t].varValue
            discharge = Dch[t].varValue
            export = E[t].varValue  # Grid export
            grid_import = G[t].varValue  # Grid import
            soc = SoC[t + 1].varValue
            consumption = C_t[t]  # House consumption from forecast
            solar = S_t[t]  # Solar production from forecast
            full_charge = FullCharge[t].varValue  # FullCharge status
            forecast_time = now + datetime.timedelta(hours=t)
            hour = forecast_time.hour
            self.log(
                f"Optimized Schedule - Hour {hour:02d}: "
                f"Consumption = {consumption:.2f} kW, "
                f"Solar = {solar:.2f} kW, "
                f"Grid Import = {grid_import:.2f} kW, "
                f"Charge from Solar = {charge_solar:.2f} kW, "
                f"Charge from Grid = {charge_grid:.2f} kW, "
                f"Discharge = {discharge:.2f} kW, "
                f"Export to Grid = {export:.2f} kW, "
                f"SoC = {soc:.2f} kWh, "
                f"Battery Full = {int(full_charge)}"
            )
            charging_schedule.append(
                {
                    "time": forecast_time,
                    "charge_solar": charge_solar,
                    "charge_grid": charge_grid,
                    "discharge": discharge,
                    "export": export,
                    "grid_import": grid_import,
                    "consumption": consumption,
                    "soc": soc,
                    "full_charge": full_charge,
                }
            )

        # Update forecast sensors with the optimization results
        self.update_forecast_sensors(charging_schedule, C_t, S_t)

        # Schedule actions based on the optimized schedule
        self.schedule_actions(charging_schedule)
        self.log("Charging and discharging actions scheduled.")

    def schedule_actions(self, schedule):
        """
        Schedules charging and discharging actions based on the optimization schedule.

        This method iterates through the optimized charging schedule and schedules
        actions (start/stop charging, enable/disable discharging) at the appropriate times.
        It ensures that actions are only scheduled for future times and updates the
        tracking state variables to prevent redundant actions.

        Args:
            schedule (list): A list of dictionaries containing scheduling information
                             for each hour in the optimization horizon.

        Returns:
            None
        """
        self.log(
            "Scheduling charging and discharging actions based on wattwise's schedule."
        )
        now = self.datetime()

        for t, entry in enumerate(schedule):
            forecast_time = entry["time"]
            action_time = forecast_time

            # Adjust action_time to the future if the time has already passed
            if action_time < now:
                continue  # Skip scheduling actions in the past

            # Desired Charging State
            desired_charging = entry["charge_grid"] > 0

            # Desired Discharging State
            desired_discharging = entry["discharge"] > 0

            # Schedule Charging Actions
            if desired_charging != self.charging_from_grid:
                if desired_charging:
                    # Schedule start charging
                    self.run_at(
                        self.start_charging,
                        action_time,
                        charge_rate=entry["charge_grid"],
                    )
                    self.log(
                        f"Scheduled START charging from grid at {action_time} with rate {entry['charge_grid']} kW."
                    )
                else:
                    # Schedule stop charging
                    self.run_at(self.stop_charging, action_time)
                    self.log(f"Scheduled STOP charging at {action_time}.")
                self.charging_from_grid = desired_charging  # Update the state

            # Schedule Discharging Actions
            if desired_discharging != self.discharging_to_house:
                if desired_discharging:
                    # Schedule enabling discharging
                    self.run_at(self.enable_discharging, action_time)
                    self.log(f"Scheduled ENABLE discharging at {action_time}.")
                else:
                    # Schedule disabling discharging
                    self.run_at(self.disable_discharging, action_time)
                    self.log(f"Scheduled DISABLE discharging at {action_time}.")
                self.discharging_to_house = desired_discharging  # Update the state

            # Handle Exporting to Grid (Optional)
            if entry["export"] > 0:
                self.log(f"Exporting {entry['export']} kW to grid at {action_time}.")
                # Implement export actions if necessary
            else:
                self.log(f"No export to grid scheduled at {action_time}.")

    def start_charging(self, kwargs):
        """
        Starts charging the battery from the grid.

        This method turns on the battery charger switch. If the charger supports setting
        a specific charge rate via a Home Assistant service, that functionality can be
        implemented here.

        Args:
            kwargs (dict): Keyword arguments containing additional parameters.
                           Expected key:
                           - charge_rate (float): The rate at which to charge the battery in kW.

        Returns:
            None
        """
        charge_rate = kwargs.get("charge_rate", self.CHARGE_RATE_MAX)
        self.log(f"Starting battery charging from grid at {charge_rate} kW.")
        # If your charger supports setting charge rate via service, implement it here.
        # Example:
        # self.call_service('charger/set_charge_rate', entity_id='charger.battery', rate=charge_rate)

        # Otherwise, simply turn on the charger switch
        self.call_service("switch/turn_on", entity_id=self.BATTERY_CHARGER_SWITCH)

    def stop_charging(self, kwargs):
        """
        Stops charging the battery from the grid.

        This method turns off the battery charger switch.

        Args:
            kwargs (dict): Keyword arguments containing additional parameters.
                           Not used in this method.

        Returns:
            None
        """
        self.log("Stopping battery charging from grid.")
        self.call_service("switch/turn_off", entity_id=self.BATTERY_CHARGER_SWITCH)

    def enable_discharging(self, kwargs):
        """
        Enables discharging of the battery to the house.

        This method turns on the battery discharger switch.

        Args:
            kwargs (dict): Keyword arguments containing additional parameters.
                           Not used in this method.

        Returns:
            None
        """
        self.log("Enabling battery discharging to the house.")
        self.call_service("switch/turn_on", entity_id=self.BATTERY_DISCHARGER_SWITCH)

    def disable_discharging(self, kwargs):
        """
        Disables discharging of the battery to the house.

        This method turns off the battery discharger switch.

        Args:
            kwargs (dict): Keyword arguments containing additional parameters.
                           Not used in this method.

        Returns:
            None
        """
        self.log("Disabling battery discharging to the house.")
        self.call_service("switch/turn_off", entity_id=self.BATTERY_DISCHARGER_SWITCH)

    def get_consumption_forecast(self, T):
        """
        Retrieves the consumption forecast for the next T hours.

        This method calculates the average consumption for each hour over the past
        seven days to generate a forecast. It retrieves historical data from Home
        Assistant and computes the average consumption per hour.

        Args:
            T (int): The number of hours to forecast.

        Returns:
            list of float: A list containing the forecasted consumption values for
                           each hour. Returns None if data retrieval fails.
        """
        self.log("Retrieving consumption forecast.")
        # Calculate average consumption over the last 7 days for each hour
        consumption = []
        now = datetime.datetime.now()
        for t in range(T):
            hour = (now + datetime.timedelta(hours=t)).hour
            total = 0
            count = 0
            for days_back in range(1, 8):  # Last 7 days
                past_date = now - datetime.timedelta(days=days_back)
                start_time = past_date.replace(
                    hour=hour, minute=0, second=0, microsecond=0
                )
                end_time = start_time + datetime.timedelta(hours=1)
                history = self.get_history(
                    self.CONSUMPTION_SENSOR, start_time, end_time
                )
                if history:
                    values = [
                        float(state.get("state", 0))
                        for state in history
                        if self.is_float(state.get("state", 0))
                    ]
                    if values:
                        avg_value = sum(values) / len(values)
                        total += avg_value
                        count += 1
            if count > 0:
                avg_consumption = total / count
            else:
                avg_consumption = 0  # Default if no data
            consumption.append(avg_consumption)
        self.log(f"Consumption forecast retrieved: {consumption}")
        return consumption

    def get_solar_production_forecast(self, T):
        """
        Retrieves the solar production forecast for the next T hours.

        This method fetches the solar production forecast data from today's and
        tomorrow's forecast sensors in Home Assistant. It combines the data and
        maps it to the next T hours, adjusting for any forecast errors.

        Args:
            T (int): The number of hours to forecast.

        Returns:
            list of float: A list containing the forecasted solar production values
                           for each hour. Returns None if data retrieval fails.
        """
        self.log("Retrieving solar production forecast.")
        # Retrieve solar production forecast from Home Assistant entities
        forecast_data_today = self.get_state(
            self.SOLAR_FORECAST_SENSOR_TODAY, attribute="detailedHourly"
        )
        forecast_data_tomorrow = self.get_state(
            self.SOLAR_FORECAST_SENSOR_TOMORROW, attribute="detailedHourly"
        )

        if not forecast_data_today:
            self.error("Solar production forecast data for today is unavailable.")
            return None

        if not forecast_data_tomorrow:
            forecast_data_tomorrow = []
            self.log(
                "Solar production forecast data for tomorrow is not available yet."
            )

        # Combine today's and tomorrow's data
        combined_forecast_data = forecast_data_today + forecast_data_tomorrow

        solar_forecast = []
        now = datetime.datetime.now(pytz.utc)
        for t in range(T):
            forecast_time = now + datetime.timedelta(hours=t)
            forecast_time = forecast_time.astimezone()
            value = None
            for entry in combined_forecast_data:
                entry_time = datetime.datetime.fromisoformat(entry["period_start"])
                entry_time = entry_time.astimezone()
                if (
                    entry_time.hour == forecast_time.hour
                    and entry_time.date() == forecast_time.date()
                ):
                    value = entry["pv_estimate"] * 1.0  # Adjust for -10% forecast error
                    break
            if value is None:
                value = 0  # Default if no forecast available
            solar_forecast.append(value)
        self.log(f"Solar production forecast retrieved: {solar_forecast}")
        return solar_forecast

    def get_energy_price_forecast(self, T):
        """
        Retrieves the energy price forecast for the next T hours.

        This method fetches the energy price forecast data from Home Assistant's
        price forecast sensor. It combines today's and tomorrow's data and maps
        it to the next T hours, converting prices from EUR/kWh to ct/kWh.

        Args:
            T (int): The number of hours to forecast.

        Returns:
            list of float: A list containing the forecasted energy prices for
                           each hour in ct/kWh. Returns None if data retrieval fails.
        """
        self.log("Retrieving energy price forecast.")
        # Retrieve energy price forecast from Home Assistant entity
        price_data_today = self.get_state(self.PRICE_FORECAST_SENSOR, attribute="today")
        price_data_tomorrow = self.get_state(
            self.PRICE_FORECAST_SENSOR, attribute="tomorrow"
        )

        if not price_data_today:
            self.error("Energy price forecast data for today is unavailable.")
            return None

        now = datetime.datetime.now()
        current_hour = now.hour

        # Combine today's and tomorrow's data
        combined_price_data = price_data_today

        if price_data_tomorrow:
            combined_price_data += price_data_tomorrow
            self.log(
                "Tomorrow's energy price data is available and included in the forecast."
            )
        else:
            self.log("Tomorrow's energy price data is not available yet.")

        # Create the price forecast for the next T hours
        price_forecast = []
        for t in range(T):
            index = current_hour + t
            if index < len(combined_price_data):
                price_entry = combined_price_data[index]
                price = price_entry["total"] * 100  # Convert EUR/kWh to ct/kWh
            else:
                # If we run out of data, use the last known price
                price = combined_price_data[-1]["total"] * 100
                self.log(
                    f"Price data for hour {index} not found. Using last known price."
                )
            price_forecast.append(price)

        self.log(f"Energy price forecast retrieved: {price_forecast}")
        return price_forecast

    def get_history(self, entity_id, start_time, end_time):
        """
        Retrieves historical state changes for a given entity within a specified time range.

        This method makes an API call to Home Assistant to fetch historical data
        for the specified entity between `start_time` and `end_time`.

        Args:
            entity_id (str): The entity ID for which to retrieve history.
            start_time (datetime.datetime): The start time for the history retrieval.
            end_time (datetime.datetime): The end time for the history retrieval.

        Returns:
            list of dict: A list of state change dictionaries for the entity.
                          Returns an empty list if no history is found or an error occurs.
        """
        self.log(f"Retrieving history for {entity_id} from {start_time} to {end_time}.")
        url = f"{self.ha_url}/api/history/period/{start_time.isoformat()}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        params = {
            "filter_entity_id": entity_id,
            "end_time": end_time.isoformat(),
            "minimal_response": "true",
        }
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            history = response.json()
            if history and len(history) > 0:
                return history[0]  # Returns a list of state changes
            else:
                self.log(
                    f"No history found for {entity_id} in the specified time range."
                )
                return []
        except requests.exceptions.RequestException as e:
            self.error(f"Error retrieving history: {e}")
            return []

    def update_forecast_sensors(
        self, charging_schedule, consumption_forecast, solar_forecast
    ):
        """
        Updates Home Assistant sensors with forecast data for visualization.

        This method processes the optimized charging schedule and forecast data,
        updating both regular sensors and binary sensors with the current state
        and forecast attributes. It ensures that the sensor states reflect the
        current values and that forecast data is available for visualization.

        Args:
            charging_schedule (list of dict): A list containing the optimized charging
                                              schedule for each hour.
            consumption_forecast (list of float): A list containing the consumption
                                                 forecast for each hour.
            solar_forecast (list of float): A list containing the solar production
                                            forecast for each hour.

        Returns:
            None
        """
        self.log("Updating forecast sensors with optimization results.")

        forecasts = {
            "sensor.wattwise_battery_charge_from_solar": [],
            "sensor.wattwise_battery_charge_from_grid": [],
            "sensor.wattwise_battery_discharge": [],
            "sensor.wattwise_grid_export": [],
            "sensor.wattwise_grid_import": [],
            "sensor.wattwise_state_of_charge": [],
            "sensor.wattwise_state_of_charge_percentage": [],
            "sensor.wattwise_consumption_forecast": [],
            "sensor.wattwise_solar_production_forecast": [],
            "sensor.wattwise_battery_full_charge_status": [],
            "binary_sensor.wattwise_battery_charging_from_grid": [],
            "binary_sensor.wattwise_battery_discharging_enabled": [],
        }

        now = self.datetime()

        # Build the forecast data
        for t, entry in enumerate(charging_schedule):
            forecast_time = entry["time"]
            timestamp_iso = forecast_time.isoformat()

            # Determine binary states
            desired_charging = entry["charge_grid"] > 0
            desired_discharging = entry["discharge"] > 0

            # Calculate SoC percentage
            soc_percentage = (entry["soc"] / self.BATTERY_CAPACITY) * 100

            # Append data to forecasts
            forecasts["sensor.wattwise_battery_charge_from_solar"].append(
                [timestamp_iso, entry["charge_solar"]]
            )
            forecasts["sensor.wattwise_battery_charge_from_grid"].append(
                [timestamp_iso, entry["charge_grid"]]
            )
            forecasts["sensor.wattwise_battery_discharge"].append(
                [timestamp_iso, entry["discharge"]]
            )
            forecasts["sensor.wattwise_grid_export"].append(
                [timestamp_iso, entry["export"]]
            )
            forecasts["sensor.wattwise_grid_import"].append(
                [timestamp_iso, entry["grid_import"]]
            )
            forecasts["sensor.wattwise_state_of_charge"].append(
                [timestamp_iso, entry["soc"]]
            )
            forecasts["sensor.wattwise_state_of_charge_percentage"].append(
                [timestamp_iso, soc_percentage]
            )
            forecasts["sensor.wattwise_battery_full_charge_status"].append(
                [timestamp_iso, entry["full_charge"]]
            )
            forecasts["binary_sensor.wattwise_battery_charging_from_grid"].append(
                [timestamp_iso, "on" if desired_charging else "off"]
            )
            forecasts["binary_sensor.wattwise_battery_discharging_enabled"].append(
                [timestamp_iso, "on" if desired_discharging else "off"]
            )
            forecasts["sensor.wattwise_consumption_forecast"].append(
                [timestamp_iso, consumption_forecast[t]]
            )
            forecasts["sensor.wattwise_solar_production_forecast"].append(
                [timestamp_iso, solar_forecast[t]]
            )

        # Update sensors
        for sensor_id, data in forecasts.items():
            # Get the current value for the sensor's state
            current_value = None
            for item in data:
                if (
                    item[0]
                    == now.replace(minute=0, second=0, microsecond=0).isoformat()
                ):
                    current_value = item[1]
                    break

            # If no current value is found, use the latest value
            if current_value is None:
                current_value = data[0][1] if data else "0"

            # Update the sensor
            self.set_state(
                sensor_id, state=current_value, attributes={"forecast": data}
            )
            self.log(f"Updated {sensor_id} with current value and forecast data.")

    def is_float(self, value):
        """
        Determines whether a given value can be converted to a float.

        This utility method attempts to convert the provided value to a float.
        It returns True if successful, otherwise False.

        Args:
            value (str): The value to check.

        Returns:
            bool: True if the value can be converted to float, False otherwise.
        """
        try:
            float(value)
            return True
        except ValueError:
            return False
