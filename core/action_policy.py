"""Bounded review of model-proposed desktop actions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import unicodedata

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
            or any(unicodedata.category(char).startswith("C") or char in "\u2028\u2029"
                   for char in value)):
        return None
    return ProposedAction(name=name, args={spec[0]: value}, preview=f"{spec[1]}: {value}")


def review_direct_action(name: str, args: object) -> ProposedAction | None:
    """Validate a direct single action using the same target boundaries."""
    if name == "power" and isinstance(args, dict) and set(args) == {"mode"}:
        labels = {"shutdown": "Shut down the computer", "restart": "Restart the computer",
                  "sleep": "Put the computer to sleep"}
        mode = args.get("mode")
        if isinstance(mode, str) and mode in labels:
            return ProposedAction(name=name, args={"mode": mode}, preview=labels[mode], risk="device_control")
    if name in {"clear_notes", "clear_reminders"} and isinstance(args, dict) and not args:
        label = "Delete all notes" if name == "clear_notes" else "Delete all reminders"
        return ProposedAction(name=name, args={}, preview=label, risk="destructive")
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
