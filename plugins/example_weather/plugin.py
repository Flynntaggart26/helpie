"""Example Weather Extended Plugin for Helpie."""
import json
from pathlib import Path


class Plugin:
    def __init__(self):
        self.api = None

    def init(self, api):
        self.api = api
        # Register commands
        api.register_command(
            "weather_forecast",
            self.weather_forecast,
            "Get 3-day weather forecast",
            ["forecast", "weather forecast", "3 day forecast", "hava tahmini"]
        )
        api.register_command(
            "weather_alerts",
            self.weather_alerts,
            "Check weather alerts for your area",
            ["weather alert", "weather warning", "hava uyarı"]
        )
        print("[WeatherExtended] Plugin loaded")

    def shutdown(self):
        print("[WeatherExtended] Plugin unloaded")

    def on_wake(self):
        """Called when wake word is detected."""
        pass

    def on_command(self, command: str, args: dict):
        """Called when a command is recognized."""
        pass

    def _get_settings(self) -> dict:
        return {
            "api_key": self.api.get_setting("api_key", ""),
            "units": self.api.get_setting("units", "metric"),
        }

    def _get_city(self) -> str:
        # Try to get city from core settings via API
        return self.api.get_setting("city", "")

    def weather_forecast(self, args: dict = None) -> str:
        """Get 3-day weather forecast."""
        settings = self._get_settings()
        api_key = settings.get("api_key", "")
        units = settings.get("units", "metric")
        city = self._get_city()

        if not api_key:
            return "Weather Extended: Please set an OpenWeatherMap API key in plugin settings."

        try:
            import requests
            url = "https://api.openweathermap.org/data/2.5/forecast"
            params = {"q": city, "appid": api_key, "units": units, "cnt": 24}
            resp = self.api.http_get("https://api.openweathermap.org/data/2.5/forecast", params=params)
            if resp["status"] != 200:
                return f"Weather API error: {resp['text']}"

            data = resp["json"]
            forecasts = []
            for item in data["list"][:8]:  # 8 * 3h = 24h
                dt = item["dt_txt"]
                temp = item["main"]["temp"]
                desc = item["weather"][0]["description"]
                forecasts.append(f"{dt}: {temp}°{'C' if settings['units']=='metric' else 'F'}, {desc}")

            return "3-day forecast for " + city + ": " + " | ".join(forecasts)
        except Exception as e:
            return f"Weather forecast failed: {e}"

    def weather_alerts(self, args: dict = None) -> str:
        """Check weather alerts."""
        settings = self._get_settings()
        api_key = settings.get("api_key", "")
        city = self._get_city()

        if not api_key:
            return "Weather Extended: Please set an OpenWeatherMap API key in plugin settings."

        try:
            import requests
            # First get coordinates
            geo_url = "https://api.openweathermap.org/geo/1.0/direct"
            geo_resp = self.api.http_get(geo_url, params={"q": city, "limit": 1, "appid": settings["api_key"]})
            if geo_resp["status"] != 200 or not geo_resp["json"]:
                return f"Could not find location: {city}"

            lat = geo_resp["json"][0]["lat"]
            lon = geo_resp["json"][0]["lon"]

            # Get alerts
            alerts_url = "https://api.openweathermap.org/data/2.5/onecall"
            alerts_resp = self.api.http_get(alerts_url, params={
                "lat": lat, "lon": lon, "appid": settings["api_key"],
                "exclude": "current,minutely,hourly,daily"
            })
            if alerts_resp["status"] != 200:
                return f"Alerts API error: {alerts_resp['text']}"

            alerts = alerts_resp["json"].get("alerts", [])
            if not alerts:
                return f"No weather alerts for {city}."

            lines = [f"⚠️ Weather alerts for {city}:"]
            for alert in alerts[:3]:
                lines.append(f"  • {alert['event']}: {alert['description'][:100]}...")
            return "\n".join(lines)
        except Exception as e:
            return f"Weather alerts failed: {e}"