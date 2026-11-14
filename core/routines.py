"""Routines / Macros: named sequences of actions with parameters."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, Optional

import config

ROUTINES_DIR = config.DATA_DIR / "routines"
ROUTINES_DIR.mkdir(parents=True, exist_ok=True)
ROUTINES_FILE = ROUTINES_DIR / "routines.json"

_lock = threading.RLock()


def _load() -> dict[str, dict]:
    if not ROUTINES_FILE.exists():
        return {}
    try:
        return json.loads(ROUTINES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    ROUTINES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_routines() -> list[dict]:
    with _lock:
        data = _load()
        return [
            {"name": name, "description": r.get("description", ""), "steps": r.get("steps", [])}
            for name, r in data.items()
        ]


def get_routine(name: str) -> Optional[dict]:
    with _lock:
        data = _load()
        return data.get(name.lower())


def save_routine(name: str, steps: list[dict], description: str = "") -> bool:
    name = name.lower().strip()
    if not name:
        return False
    with _lock:
        data = _load()
        data[name] = {"description": description, "steps": steps}
        _save(data)
    return True


def delete_routine(name: str) -> bool:
    name = name.lower().strip()
    with _lock:
        data = _load()
        if name not in data:
            return False
        del data[name]
        _save(data)
    return True


def run_routine(name: str, params: dict = None, executor: Callable[[str, dict], str] = None) -> str:
    """Execute a routine by name. `executor(step_name, step_args)` runs each step."""
    routine = get_routine(name)
    if not routine:
        return f"Routine '{name}' not found."
    steps = routine.get("steps", [])
    if not steps:
        return f"Routine '{name}' has no steps."
    params = params or {}
    results = []
    for i, step in enumerate(steps):
        step_name = step.get("action", "")
        step_args = dict(step.get("args", {}))
        # Substitute {param} placeholders
        for key, value in params.items():
            step_args = {k: (v.replace(f"{{{key}}}", str(value)) if isinstance(v, str) else v)
                         for k, v in step_args.items()}
        if executor:
            try:
                result = executor(step_name, step_args)
            except Exception as e:
                result = f"Step {i+1} ({step_name}) failed: {e}"
        else:
            result = f"[dry-run] {step_name} {step_args}"
        results.append(f"Step {i+1}: {result}")
    return " | ".join(results)


# Built-in action aliases for routines
ROUTINE_ACTIONS = {
    "open_app": {"action": "open_app", "args": {"app": "{app}"}},
    "close_app": {"action": "close_app", "args": {"app": "{app}"}},
    "web_search": {"action": "web_search", "args": {"query": "{query}", "engine": "google"}},
    "open_site": {"action": "open_site", "args": {"name": "{site}"}},
    "set_volume": {"action": "set_volume", "args": {"percent": "{level}"}},
    "volume": {"action": "volume", "args": {"direction": "{direction}"}},
    "set_brightness": {"action": "set_brightness", "args": {"percent": "{level}"}},
    "brightness": {"action": "brightness", "args": {"direction": "{direction}"}},
    "screenshot": {"action": "screenshot", "args": {}},
    "lock_screen": {"action": "lock_screen", "args": {}},
    "sleep": {"action": "sleep_pc", "args": {}},
    "shutdown": {"action": "shutdown_pc", "args": {}},
    "restart": {"action": "shutdown_pc", "args": {"restart": True}},
    "add_note": {"action": "add_note", "args": {"text": "{text}"}},
    "remind": {"action": "set_timer", "args": {"minutes": "{minutes}", "label": "{label}"}},
    "read_clipboard": {"action": "read_clipboard", "args": {}},
    "write_clipboard": {"action": "write_clipboard", "args": {"text": "{text}"}},
    "speak": {"action": "speak", "args": {"text": "{text}"}},
    "wait": {"action": "wait", "args": {"seconds": "{seconds}"}},
}


TEMPLATES = {
    "start_work": {
        "description": "Open work apps and set environment",
        "steps": [
            {"action": "open_app", "args": {"app": "code"}},
            {"action": "open_app", "args": {"app": "chrome"}},
            {"action": "set_volume", "args": {"percent": 30}},
        ],
    },
    "end_work": {
        "description": "Close work apps and cleanup",
        "steps": [
            {"action": "close_app", "args": {"app": "code"}},
            {"action": "close_app", "args": {"app": "chrome"}},
            {"action": "set_volume", "args": {"percent": 50}},
        ],
    },
    "meeting_prep": {
        "description": "Prepare for a meeting",
        "steps": [
            {"action": "open_app", "args": {"app": "chrome"}},
            {"action": "set_volume", "args": {"percent": 50}},
            {"action": "screenshot", "args": {}},
        ],
    },
    "focus_mode": {
        "description": "Minimize distractions",
        "steps": [
            {"action": "set_volume", "args": {"percent": 20}},
            {"action": "brightness", "args": {"direction": "down"}},
        ],
    },
}


def list_templates() -> dict[str, dict]:
    """Built-in routine templates, available to the UI."""
    return {name: {"description": t["description"], "steps": t["steps"]} for name, t in TEMPLATES.items()}


def create_routine_from_template(name: str, template: str, params: dict = None) -> bool:
    """Create a routine from a built-in template."""
    tpl = TEMPLATES.get(template)
    if not tpl:
        return False
    return save_routine(name, tpl["steps"], tpl["description"])