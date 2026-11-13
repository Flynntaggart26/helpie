"""Settings load/save."""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"
NOTES_PATH = DATA_DIR / "notes.md"
PORT_PATH = DATA_DIR / "port.txt"

DEFAULTS = {
    "user_name": "",
    "provider": "gemini",
    "api_key": "",
    "model": "gemini-flash-latest",
    "voice": "en-US-AriaNeural",
    "rate": "+0%",
    "volume": 0.9,
    "mic_index": None,
    "language": "en-US",
    "hotkey": "ctrl+h",
    "auto_listen": True,
    "continuous": True,
    "auto_turns": 3,
    "city": "",
    "check_updates": True,
    "window": {"x": None, "y": None},
    "first_run": True,
}


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = dict(DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            cfg = _merge(cfg, json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("HELPIE_API_KEY", "")
    return cfg


def save(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean = dict(cfg)
    clean.pop("_mics", None)
    SETTINGS_PATH.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def notes_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return NOTES_PATH
