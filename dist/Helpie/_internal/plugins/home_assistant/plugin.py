"""Home Assistant Plugin for Helpie - Control lights, switches, climate, sensors."""
import json
import threading
from typing import Optional


class Plugin:
    def __init__(self):
        self.api = None
        self._base_url = ""
        self._headers = None
        self._verify_ssl = True

    def init(self, api):
        self.api = api
        self._load_config()
        api.register_command(
            "turn_on",
            self.turn_on,
            "Turn on a light/switch/entity",
            ["turn on ", "open ", "aç ", "hass turn on "]
        )
        api.register_command(
            "turn_off",
            self.turn_off,
            "Turn off a light/switch/entity",
            ["turn off ", "close ", "kapat ", "hass turn off "]
        )
        api.register_command(
            "toggle",
            self.toggle,
            "Toggle a light/switch/entity",
            ["toggle ", "hass toggle "]
        )
        api.register_command(
            "set_light",
            self.set_light,
            "Set light brightness/color",
            ["set light ", "light brightness ", "ışık ", "ışığı "]
        )
        api.register_command(
            "set_climate",
            self.set_climate,
            "Set climate temperature/mode",
            ["set climate ", "set temperature ", "klima ", "sıcaklık "]
        )
        api.register_command(
            "get_state",
            self.get_state,
            "Get state of an entity",
            ["state of ", "status of ", "hass state ", "durum "]
        )
        api.register_command(
            "list_entities",
            self.list_entities,
            "List entities by domain",
            ["list lights", "list switches", "list entities", "hass list "]
        )
        api.register_command(
            "call_service",
            self.call_service,
            "Call any Home Assistant service",
            ["hass call ", "hass service "]
        )
        print("[HomeAssistant] Plugin loaded")

    def shutdown(self):
        print("[HomeAssistant] Plugin unloaded")

    def _load_config(self):
        settings = self._get_settings()
        self._base_url = settings.get("url", "http://homeassistant.local:8123").rstrip("/")
        token = settings.get("token", "")
        self._verify_ssl = settings.get("verify_ssl", True)
        if token:
            self._headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        else:
            self._headers = None

    def _get_settings(self) -> dict:
        return {
            "url": self.api.get_setting("url", "http://homeassistant.local:8123"),
            "token": self.api.get_setting("token", ""),
            "verify_ssl": self.api.get_setting("verify_ssl", True),
        }

    def _ha_request(self, method: str, endpoint: str, json_data: dict = None) -> dict:
        if not self._headers:
            return {"error": "Not authenticated. Set Home Assistant token in Settings."}
        import requests
        url = f"{self._base_url}/api{endpoint}"
        try:
            resp = requests.request(method, url, headers=self._headers, json=json_data, timeout=10, verify=self._verify_ssl)
            if resp.status_code == 401:
                return {"error": "Invalid token"}
            return {"status": resp.status_code, "json": resp.json() if resp.content else {}}
        except Exception as e:
            return {"error": str(e)}

    def _resolve_entity_id(self, name: str) -> str:
        """Try to resolve a friendly name to entity_id."""
        # First try exact match
        result = self._ha_request("GET", "/states")
        if result.get("status") == 200:
            for entity in result["json"]:
                if entity.get("entity_id", "").lower() == name.lower():
                    return entity["entity_id"]
                if entity.get("attributes", {}).get("friendly_name", "").lower() == name.lower():
                    return entity["entity_id"]
        # Return as-is if not found (might be entity_id already)
        return name

    def turn_on(self, args: dict = None) -> str:
        entity = (args or {}).get("entity", "").strip()
        if not entity:
            return "Entity required. Try 'turn on living room light'."
        entity_id = self._resolve_entity_id(entity)
        result = self._ha_request("POST", f"/services/homeassistant/turn_on", json_data={"entity_id": entity_id})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") in (200, 201):
            return f"Turned on {entity}."
        return f"Failed: {result['json']}"

    def turn_off(self, args: dict = None) -> str:
        entity = (args or {}).get("entity", "").strip()
        if not entity:
            return "Entity required. Try 'turn off living room light'."
        entity_id = self._resolve_entity_id(entity)
        result = self._ha_request("POST", f"/services/homeassistant/turn_off", json_data={"entity_id": entity_id})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") in (200, 201):
            return f"Turned off {entity}."
        return f"Failed: {result['json']}"

    def toggle(self, args: dict = None) -> str:
        entity = (args or {}).get("entity", "").strip()
        if not entity:
            return "Entity required. Try 'toggle living room light'."
        entity_id = self._resolve_entity_id(entity)
        result = self._ha_request("POST", f"/services/homeassistant/toggle", json_data={"entity_id": entity_id})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") in (200, 201):
            return f"Toggled {entity}."
        return f"Failed: {result['json']}"

    def set_light(self, args: dict = None) -> str:
        entity = (args or {}).get("entity", "").strip()
        if not entity:
            return "Light entity required. Try 'set light living room brightness 50'."
        entity_id = self._resolve_entity_id(entity)

        # Parse brightness and color
        import re
        text = (args or {}).get("text", "") or (args or {}).get("entity", "")
        brightness = None
        color = None
        temp = None

        bright_match = re.search(r"brightness\s+(\d{1,3})|%?\s*(\d{1,3})\s*%?", (args or {}).get("text", ""))
        if bright_match:
            brightness = max(1, min(255, int(bright_match.group(1) or bright_match.group(2))))

        temp_match = re.search(r"temperature\s+(\d{3,4})|kelvin\s+(\d{3,4})", (args or {}).get("text", ""))
        if temp_match:
            temp = int(temp_match.group(1) or temp_match.group(2))

        data = {"entity_id": entity_id}
        if brightness is not None:
            data["brightness"] = brightness
        if temp is not None:
            data["color_temp"] = temp

        result = self._ha_request("POST", "/services/light/turn_on", json_data=data)
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") in (200, 201):
            msg = f"Light set"
            if brightness: msg += f" brightness {brightness}"
            if temp: msg += f" temp {temp}K"
            return msg + "."
        return f"Failed: {result['json']}"

    def set_climate(self, args: dict = None) -> str:
        entity = (args or {}).get("entity", "").strip()
        if not entity:
            return "Climate entity required. Try 'set climate living room to 22 degrees'."
        entity_id = self._resolve_entity_id(entity)

        import re
        text = (args or {}).get("text", "")
        temp_match = re.search(r"(\d{1,2}(?:\.\d)?)\s*(?:degrees?|celsius|c|°c)", text, re.I)
        temp = float(temp_match.group(1)) if temp_match else None

        mode_match = re.search(r"mode\s+(heat|cool|auto|off|fan_only|dry)", text, re.I)
        mode = mode_match.group(1).lower() if mode_match else None

        data = {"entity_id": entity_id}
        if temp is not None:
            data["temperature"] = temp
        if mode:
            data["hvac_mode"] = mode

        result = self._ha_request("POST", "/services/climate/set_temperature" if temp else "/services/climate/set_hvac_mode", json_data=data)
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") in (200, 201):
            msg = "Climate set"
            if temp: msg += f" to {temp}°C"
            if mode: msg += f" mode {mode}"
            return msg + "."
        return f"Failed: {result['json']}"

    def get_state(self, args: dict = None) -> str:
        entity = (args or {}).get("entity", "").strip()
        if not entity:
            return "Entity required. Try 'state of living room light'."
        entity_id = self._resolve_entity_id(entity)
        result = self._ha_request("GET", f"/states/{entity_id}")
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Entity not found: {entity_id}"
        state = result["json"]
        attrs = state.get("attributes", {})
        friendly = attrs.get("friendly_name", entity_id)
        state_val = state.get("state", "unknown")
        lines = [f"{friendly} ({entity_id}): {state_val}"]
        for k, v in attrs.items():
            if k not in ("friendly_name", "supported_features") and not k.startswith("_"):
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    def list_entities(self, args: dict = None) -> str:
        domain = (args or {}).get("domain", "").strip()
        result = self._ha_request("GET", "/states")
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Failed: {result['json']}"
        entities = result["json"]
        if domain:
            entities = [e for e in entities if e["entity_id"].startswith(domain + ".")]
        if not entities:
            return f"No entities found{' for ' + domain if domain else ''}."
        lines = [f"🏠 Entities ({len(entities)}):"]
        for e in sorted(entities, key=lambda x: x["entity_id"])[:30]:
            attrs = e.get("attributes", {})
            friendly = attrs.get("friendly_name", e["entity_id"])
            state = e["state"]
            lines.append(f"  {e['entity_id']}: {state} ({friendly})")
        if len(entities) > 30:
            lines.append(f"  ... and {len(entities) - 30} more")
        return "\n".join(lines)

    def call_service(self, args: dict = None) -> str:
        """Call any HA service: domain/service entity_id=... key=value..."""
        text = (args or {}).get("text", "").strip()
        if not text:
            return "Usage: hass call domain/service entity_id=... key=value..."
        parts = text.split()
        if len(parts) < 2:
            return "Usage: hass call domain/service entity_id=... key=value..."
        service = parts[1]
        entity_id = None
        data = {}
        for part in parts[2:]:
            if "=" in part:
                k, v = part.split("=", 1)
                if k == "entity_id":
                    entity_id = v
                else:
                    # Try to parse as JSON value
                    try:
                        data[k] = json.loads(v)
                    except:
                        data[k] = v
        if entity_id:
            data["entity_id"] = entity_id
        domain, service_name = service.split("/", 1) if "/" in service else ("homeassistant", service)
        result = self._ha_request("POST", f"/services/{domain}/{service}", json_data=data)
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") in (200, 201):
            return f"Service {service} called."
        return f"Failed: {result['json']}"