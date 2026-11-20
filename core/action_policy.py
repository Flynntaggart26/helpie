"""Bounded review of model-proposed desktop actions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import unicodedata
from urllib.parse import urlsplit

# Routines may only run these bounded, local actions without a separate review.
ROUTINE_ALLOWED_ACTIONS = frozenset({
    "open_app", "close_app", "switch_window", "set_volume", "volume",
    "set_brightness", "add_note", "set_timer", "set_reminder", "what_time",
    "calculate", "battery", "system_info", "read_reminders",
})

# Plugin commands are Python code running with Helpie's privileges. Only these
# reviewed read operations may run through chat until action-bound approval exists.
READ_ONLY_PLUGIN_COMMANDS = frozenset({
    ("system_monitor", "system_stats"), ("system_monitor", "system_top_processes"),
    ("example_weather", "weather_forecast"), ("example_weather", "weather_alerts"),
    ("clipboard_history", "clipboard_history"), ("email_calendar", "read_email"),
    ("email_calendar", "calendar_events"), ("github", "list_issues"),
    ("github", "list_prs"), ("github", "search_repos"), ("github", "get_repo"),
    ("github", "list_repos"), ("notion", "search"), ("notion", "read_page"),
    ("home_assistant", "get_state"), ("home_assistant", "list_entities"),
    ("spotify", "current_track"), ("spotify", "playlists"), ("ollama", "list_models"),
})


@dataclass(frozen=True)
class ProposedAction:
    name: str
    args: dict[str, Any]
    preview: str
    risk: str = "reversible_local"


def review_model_action(name: str, args: object) -> ProposedAction | None:
    """Accept only simple, single actions with complete, printable targets."""
    fields = {"open_app": ("app", "Open app"), "close_app": ("app", "Close app"),
              "switch_window": ("name", "Switch to window")}
    spec = fields.get(name)
    if spec is None or not isinstance(args, dict) or set(args) != {spec[0]}:
        return None
    value = args[spec[0]]
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (not value or len(value) > 80
            or any(char in value for char in "/\\:")
            or any(unicodedata.category(char).startswith("C") or char in "\u2028\u2029"
                   for char in value)):
        return None
    return ProposedAction(name=name, args={spec[0]: value}, preview=f"{spec[1]}: {value}")


def review_direct_action(name: str, args: object) -> ProposedAction | None:
    """Validate a direct single action using the same target boundaries."""
    if name == "web_search" and isinstance(args, dict) and set(args) == {"query", "engine"}:
        query, engine = args["query"], args["engine"]
        if (isinstance(query, str) and 1 < len(query) <= 500 and query == query.strip()
                and isinstance(engine, str) and engine in {"google", "youtube"}
                and not any(unicodedata.category(c).startswith("C") or c in "\u2028\u2029" for c in query)):
            return ProposedAction(name, {"query": query, "engine": engine},
                                  f"Send this search to {engine.title()}: {query}", "external_communication")
    if name == "open_url" and isinstance(args, dict) and set(args) == {"url"}:
        url = args["url"]
        if not isinstance(url, str) or not 1 <= len(url) <= 2048 or url != url.strip():
            return None
        if any(c.isspace() or c == "\\" or unicodedata.category(c).startswith("C") for c in url):
            return None
        if url.lower().startswith("www."):
            url = "https://" + url
        try:
            parts = urlsplit(url)
            if (parts.scheme not in {"http", "https"} or not parts.hostname
                    or parts.username is not None or parts.password is not None
                    or parts.port is not None and not 1 <= parts.port <= 65535):
                return None
        except ValueError:
            return None
        return ProposedAction(name, {"url": url}, f"Open this link: {url}", "external_communication")
    if name == "power" and isinstance(args, dict) and set(args) == {"mode"}:
        labels = {"shutdown": "Shut down the computer", "restart": "Restart the computer",
                  "sleep": "Put the computer to sleep"}
        mode = args.get("mode")
        if isinstance(mode, str) and mode in labels:
            return ProposedAction(name=name, args={"mode": mode}, preview=labels[mode], risk="device_control")
    if name in {"clear_notes", "clear_reminders", "clear_memory"} and isinstance(args, dict) and not args:
        label = {"clear_notes": "Delete all notes", "clear_reminders": "Delete all reminders",
                 "clear_memory": "Delete all saved memories"}[name]
        return ProposedAction(name=name, args={}, preview=label, risk="destructive")
    if name in {"forget_memory", "delete_routine"} and isinstance(args, dict):
        key = "text" if name == "forget_memory" else "name"
        value = args.get(key)
        if (set(args) == {key} and isinstance(value, str) and 1 <= len(value) <= 200
                and value == value.strip() and not any(unicodedata.category(c).startswith("C")
                or c in "\u2028\u2029" for c in value)):
            label = "Forget exact memory" if name == "forget_memory" else "Delete routine"
            return ProposedAction(name=name, args={key: value}, preview=f"{label}: {value}", risk="destructive")
    if name == "empty_recycle_bin" and isinstance(args, dict) and not args:
        return ProposedAction(name=name, args={}, preview="Permanently empty the Recycle Bin",
                              risk="destructive")
    return review_model_action(name, args)


def confirmation(text: str) -> str | None:
    normalized = text.strip().lower().strip(" .!?…")
    if normalized in {"yes", "yeah", "yep", "sure", "do it", "confirm", "ok", "okay",
                      "evet", "onayla", "onaylıyorum", "tamam", "doğru"}:
        return "yes"
    if normalized in {"no", "nope", "cancel", "stop", "never mind", "don't",
                      "hayır", "hayir", "vazgeç", "vazgec", "iptal", "dur", "yok"}:
        return "no"
    return None
