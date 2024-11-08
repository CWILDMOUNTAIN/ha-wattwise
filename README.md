# WattWise 
![WattWise Logo](images/wattwise.png) 

![GitHub License](https://img.shields.io/github/license/bullitt186/ha-wattwise?style=for-the-badge)![GitHub commit activity](https://img.shields.io/github/commit-activity/y/bullitt186/ha-wattwise?style=for-the-badge)![Maintenance](https://img.shields.io/maintenance/yes/2024?style=for-the-badge)

WattWise is an AppDaemon application for [Home Assistant](https://www.home-assistant.io/)  that intelligently optimizes battery usage based on consumption forecasts, solar production forecasts, and dynamic energy prices. By leveraging historical data and real-time information, it schedules battery charging and discharging actions to minimize energy costs and maximize efficiency, providing seamless integration and real-time monitoring through Home Assistant's interface.

## Table of Contents 
 
- [Features](README.md#features)
 
- [How It Works](README.md#how-it-works)
 
- [Getting Started](README.md#getting-started)  
  - [Prerequisites](README.md#prerequisites)
 
  - [Installation](README.md#installation)
 
- [Configuration](README.md#configuration)  
  - [Customizing WattWise](README.md#customizing-wattwise)
 
- [Usage](README.md#usage)  
  - [Setting Up Input Booleans and Binary Sensors](README.md#setting-up-input-booleans-and-binary-sensors)
 
  - [Automations for Battery Control](README.md#automations-for-battery-control)
 
  - [Visualizing Forecasts](README.md#visualizing-forecasts)
 
- [Contributing](README.md#contributing)
 
- [License](README.md#license)
 
- [Contact](README.md#contact)
 
- [Acknowledgements](README.md#acknowledgements)

## Features 
 
- **Hourly Optimization** : Executes the optimization process every hour to ensure decisions are based on the latest data.
 
- **Dynamic Forecasting** : Utilizes historical consumption data, solar production forecasts, and real-time energy prices.
 
- **Automated Charging & Discharging** : Schedules battery charging from the grid or solar and discharging to the house based on optimization results.
 
- **Real-Time Monitoring** : Updates Home Assistant sensors with current values and forecast data for comprehensive monitoring.
 
- **Customizable Parameters** : Adjust battery capacity, charge/discharge rates, tariffs, and more to fit your specific setup via configuration.
 
- **User-Friendly Visualization** : Integrates with [ApexCharts](https://github.com/RomRider/apexcharts-card)  for intuitive graphical representations of forecasts and actions.

## How It Works 

WattWise leverages linear programming to optimize the charging and discharging schedule of your home battery system. Here's a detailed explanation of the process:
 
1. **Data Collection** : 
  - **Consumption Forecast** : Calculates average consumption for each hour based on historical data from the past seven days.
 
  - **Solar Production Forecast** : Retrieves solar production forecasts for today and tomorrow from Home Assistant sensors.
 
  - **Energy Price Forecast** : Obtains current and future energy prices, considering both today's and tomorrow's rates.
 
2. **Optimization Algorithm** : 
  - **Objective** : Minimizes the total energy cost over a 24-hour horizon by determining the optimal times to charge (from solar or grid) and discharge the battery.
 
  - **Constraints** : 
    - **Battery Capacity** : Ensures the battery state of charge (SoC) stays within physical limits.
 
    - **Charge/Discharge Rates** : Respects maximum charge and discharge rates of the battery system.
 
    - **Energy Balance** : Maintains a balance between consumption, production, and battery/storage actions.
 
    - **Grid Interactions** : Manages energy import/export to/from the grid, considering feed-in tariffs.
 
3. **Scheduling Actions** : 
  - **Charging from Grid** : Schedules charging during periods of low energy prices or when solar production is insufficient.
 
  - **Discharging to House** : Schedules discharging during periods of high consumption or high energy prices.
 
  - **Updating States** : Adjusts Home Assistant sensors to reflect the optimized schedule and current statuses.
 
4. **Real-Time Updates** : 
  - **Sensor States** : Updates custom sensors with current values and forecasts, providing real-time insights.
 
  - **Visualization** : Enables graphical representations through ApexCharts for better understanding and monitoring.

## Getting Started 

### Prerequisites 
 
- **Home Assistant** : A running instance of [Home Assistant](https://www.home-assistant.io/) .
 
- **HACS** : [Home Assistant Community Store](https://www.hacs.xyz/)  installed.
 
- **HA Solcast PV Solar Forecast Integration** : Installed via HACS and configured, so that you get an accurate PV production forecast. The script expects the forecast information in the format provided by [Solcast](https://github.com/BJReplay/ha-solcast-solar) .
 
- **Tibber API Token** : You need an API Token from Tibber to fetch your energy price forecast. You can get your token from [Tibber's Dev Portal](https://developer.tibber.com/settings/access-token). Place your token in ``config/secrets.yaml`` like this:

```
tibber_token: abcd1234efgh5678ijkl9012mnop3456qrst7890uvw
```
 
- **AppDaemon** :
  - Search for the “AppDaemon 4” add-on in the Home Assistant add-on store and install it.

  - Start the “AppDaemon 4” add-on.

  - Check the logs of the “AppDaemon 4” add-on to see if everything went well.
 
  - [Relevant Forum Entry](https://community.home-assistant.io/t/home-assistant-community-add-on-appdaemon-4/163259)

### Installation 
 
1. **AppDaemon Python Packages** Under **Settings**  → **Add-Ons**  → **AppDaemon**  → **Configuration** : 
  - **System Packages** : Add `musl-dev`, `gcc`, `glpk`
 
  - **Python Packages** : Add `pulp`, `numpy==1.26.4`, `tzlocal`
 
2. **Set up WattWise in AppDaemon**  
  - Place `wattwise.py` (the WattWise script) in your AppDaemon apps directory (e.g., `/config/appdaemon/apps/` or `/root/addon_configs/a0d7b954_appdaemon/apps/`). You can do this via SSH or via the Visual Studio Code AddOns.
 
  - Configure the app in `apps.yaml` in the same folder. Define your user-specific settings here.

```yaml
wattwise:
  module: wattwise
  class: WattWise
  ha_url: "http://your-home-assistant-url:8123"
  token: "YOUR_LONG_LIVED_ACCESS_TOKEN"
  # User-specific settings
  battery_capacity: 11.2  # kWh
  battery_efficiency: 0.9
  charge_rate_max: 6  # kW
  discharge_rate_max: 6  # kW
  time_horizon: 48  # hours
  feed_in_tariff: 7  # ct/kWh
  consumption_history_days: 7  # days
  lower_battery_limit: 1.0  # kWh
  # Home Assistant Entity IDs
  consumption_sensor: "sensor.your_house_consumption"
  solar_forecast_sensor_today: "sensor.solcast_pv_forecast_today"
  solar_forecast_sensor_tomorrow: "sensor.solcast_pv_forecast_tomorrow"
  price_forecast_sensor: "sensor.tibber_prices"
  battery_soc_sensor: "sensor.your_battery_soc"
  # Optional switches (default values shown)
  battery_charging_switch: "input_boolean.wattwise_battery_charging_from_grid"
  battery_discharging_switch: "input_boolean.wattwise_battery_discharging_enabled"
```
 
  - **Explanation** : 
    - **`module`**  and ****`module`**  and `class`** : Point to your WattWise app module and class.
 
    - **`ha_url`**  and ****`ha_url`**  and `token`** : Your Home Assistant URL and a long-lived access token for API access.
 
    - **User-specific settings** : All the constants specific to your solar/electric system are defined here. Adjust them according to your setup.
 
    - **Home Assistant Entity IDs** : Replace the entity IDs with your own Home Assistant sensors and switches.
 
1. **Configure Home Assistant Sensors**  
  - Place `wattwise.yaml` in your `/config/packages/` folder. If the folder does not exist, create it.
 
  - Edit your `configuration.yaml` file of Home Assistant and add the packages statement in the `homeassistant` section:

```yaml
homeassistant:
  packages: !include_dir_named packages
```
 
4. **Restart Services**  
  - **Home Assistant** : Restart to apply sensor configurations.
 
  - **AppDaemon** : Restart to load the WattWise application.

## Configuration 

Proper configuration is essential for WattWise to function correctly. Below are the key areas you need to configure.

### Customizing WattWise 
You can adjust various parameters within the `apps.yaml` configuration file to match your specific setup. Below is a list of configuration parameters that you can set in your `apps.yaml` file under the `wattwise` app: 
- **Battery Parameters** : 
  - **`battery_capacity`**  (float): Total capacity of your battery in kWh. Example: `11.2`
 
  - **`battery_efficiency`**  (float): Efficiency factor of your battery (0 < efficiency ≤ 1). Example: `0.9`
 
  - **`charge_rate_max`**  (float): Maximum charging rate of your battery in kW. Example: `6`
 
  - **`discharge_rate_max`**  (float): Maximum discharging rate of your battery in kW. Example: `6`
 
  - **`lower_battery_limit`**  (float): The algorithm will leave this amount of kWh in the battery to allow some buffer in case real-world consumption exceeds the forecasted consumption. Set this to `0` if you want to use the full battery capacity. Example: `1.0`
 
- **Time Horizon** : 
  - **`time_horizon`**  (int): Number of hours to look ahead in the optimization (default is 48 hours). Note that the time horizon will be truncated in each run to the highest seen forecast horizon for solar production or prices. Example: `48`
 
  - **`consumption_history_days`**  (int): Number of days in the past to calculate the average consumption (default is 7 days). Example: `7`
 
- **Tariffs and Prices** : 
  - **`feed_in_tariff`**  (float): Price for feeding energy back to the grid in ct/kWh. Only static feed-in tariffs are supported currently. Example: `7`
 
- **Entity IDs** : 
  - **`consumption_sensor`**  (string): Entity ID for your house's energy consumption sensor. Example: `"sensor.your_house_consumption"`
 
  - **`solar_forecast_sensor_today`**  (string): Entity ID for today's solar production forecast. Must be in the format provided by Solcast. Example: `"sensor.solcast_pv_forecast_today"`
 
  - **`solar_forecast_sensor_tomorrow`**  (string): Entity ID for tomorrow's solar production forecast. Example: `"sensor.solcast_pv_forecast_tomorrow"`
 
  - **`price_forecast_sensor`**  (string): Entity ID for energy price forecast data. Must be in the format provided by Tibber. Example: `"sensor.tibber_prices"`
 
  - **`battery_soc_sensor`**  (string): Entity ID for the battery state of charge sensor. Example: `"sensor.your_battery_soc"`
 
- **Battery Charger/Discharger Switches** : 
  - **`battery_charging_switch`**  (string): Entity ID for the switch that controls battery charging from the grid. Default: `"input_boolean.wattwise_battery_charging_from_grid"`
 
  - **`battery_discharging_switch`**  (string): Entity ID for the switch that controls battery discharging to the house. Default: `"input_boolean.wattwise_battery_discharging_enabled"`

#### After Configuration 
After making changes to the `apps.yaml` file, restart AppDaemon to apply the updates.
## Usage 

Once installed and configured, WattWise automatically runs the optimization process every hour and on Home Assistant restart. It analyzes consumption patterns, solar production forecasts, and energy prices to determine the most cost-effective charging and discharging schedule for your battery system.
You can also trigger a manual update by firing the event `MANUAL_BATTERY_OPTIMIZATION` or, for convenience, using `input_boolean.wattwise_manual_optimization` as a button in the UI.

### Automations for Battery Control 
You need to configure automations based on `binary_sensor.wattwise_battery_charging_from_grid`, `binary_sensor.wattwise_battery_discharging_enabled`, and/or `sensor.wattwise_battery_charge_from_grid`, `sensor.wattwise_battery_discharge` to actually control your local system.

**Example Automations:**

You can find example automations in the files `example_automation_e3dc_charge_from_grid.yaml` and `example_automation_e3dc_discharge_control.yaml`. These examples show how to control an E3DC Hauskraftwerk using [Torben Nehmer's hacs-e3dc integration](https://github.com/torbennehmer/hacs-e3dc) .
### Visualizing Forecasts 
Integrate with [ApexCharts](https://github.com/RomRider/apexcharts-card)  in Home Assistant to visualize forecast data and optimized schedules. You also need [lovelace-card-templater](https://github.com/gadgetchnnel/lovelace-card-templater)  for dynamic time horizons.You can find the YAML for the following card in the file `wattwise-history-forecast-chart.yaml`. This visualization uses several entities, so you will need to adjust them to match your PV system.![WattWise Forecast Chart](images/wattwise-history-forecast-chart.png) 

## Contributing 

Contributions are welcome! Whether it's reporting bugs, suggesting features, or submitting pull requests, your input helps improve WattWise.
 
1. **Fork the Repository**
 
2. **Create a Feature Branch** 

```bash
git checkout -b feature/YourFeature
```
 
3. **Commit Your Changes** 

```bash
git commit -m "Add Your Feature"
```
 
4. **Push to the Branch** 

```bash
git push origin feature/YourFeature
```
 
5. **Open a Pull Request**

Please ensure that your contributions adhere to the project's coding standards and include appropriate documentation.

## License 
This project is licensed under the [AGPL-3.0 license](https://www.gnu.org/licenses/agpl-3.0.html.en#license-text) .
## Contact 
 
- **GitHub** : [bullitt168](https://github.com/bullitt168)

## Acknowledgements 
 
- [AppDaemon](https://appdaemon.readthedocs.io/en/latest/)
 
- [Home Assistant](https://www.home-assistant.io/)
 
- [SolCast](https://github.com/BJReplay/ha-solcast-solar)
 
- [ApexCharts Card](https://github.com/RomRider/apexcharts-card)