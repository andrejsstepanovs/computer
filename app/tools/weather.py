import requests
from typing import Optional
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from app.config import Configuration
import datetime


class WeatherTool(BaseTool):
    """Tool that gets current and upcoming weather."""

    name: str = "weather"
    description: str = (
        "A wrapper around Weather Search. "
        "Useful for when you need to know current or upcoming weather. "
        "Input should be location."
    )
    cache: str = ""
    config: Configuration = None

    def _run(
        self,
        location: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Use the tool."""
        if not self.cache:
            location = self.config.prompt_replacements["location"]
            location = location.replace(",", "").replace(" ", "-")
            response = requests.get(f"https://wttr.in/{location}?format=j1")

            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            weather_info = [f"Current time is {current_time}"]
            if response.status_code == 200:
                data = response.json()
                for area in data['nearest_area']:
                    location_info = []
                    for location in area['areaName']:
                        location_info.append(location['value'])
                    for country in area['country']:
                        location_info.append(country['value'])
                    weather_info.append("Location: ".join(location_info))
                    weather_info.append("")

                weather_info.append("# Current Weather:")
                for current_condition in data['current_condition']:
                    for description in current_condition['weatherDesc']:
                        weather_info.append(f"- Condition: {description['value']}")
                    weather_info.append(f"- Temperature (°C): {current_condition['temp_C']}")
                    weather_info.append(f"- Humidity: {current_condition['humidity']}")
                    weather_info.append(f"- Cloud Cover (%): {current_condition['cloudcover']}")
                    weather_info.append(f"- Wind Speed (km/h): {current_condition['windspeedKmph']}")
                    weather_info.append("# Forecast:")
                    for current_condition in data['weather']:
                        weather_info.append(f"- {current_condition['date']}")
                        for description in current_condition['hourly']:
                            time = str(description['time']).zfill(4)
                            weather_info.append(
                                f"-- {time[:2]}:{time[2:]}: {description['weatherDesc'][0]['value']}, {description['tempC']}°C, {description['chanceofrain']}% rain, {description['windspeedKmph']} km/h")

            self.cache = "\n".join(weather_info)

        return self.cache