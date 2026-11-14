"""Settings load/save (the API key is encrypted with Windows DPAPI)."""
from __future__ import annotations

import json
import os
from pathlib import Path

try:  # core/secrets.py (DPAPI), not the stdlib module
    import secrets as dpapi
except Exception:  # pragma: no cover
    dpapi = None

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
    "background_apps": True,
    "auto_turns": 3,
    "city": "",
    "check_updates": True,
    "window": {"x": None, "y": None},
    "first_run": True,
    "wake_word": True,
    "wake_word_access_key": "",
    "theme": "dark",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.2",
    "openai_url": "",
    "openai_key": "",
    "openai_model": "",
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
    raw: dict = {}
    if SETTINGS_PATH.exists():
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            cfg = _merge(cfg, raw)
        except (json.JSONDecodeError, OSError):
            raw = {}

    encrypted = str(raw.get("api_key_enc") or "")
    plaintext = str(cfg.get("api_key") or "")
    if encrypted and dpapi:
        decrypted = dpapi.unprotect(encrypted)
        if decrypted:
            cfg["api_key"] = decrypted
    elif plaintext and dpapi:
        # Migrate an old plaintext key to DPAPI on first run.
        save(cfg)

    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("HELPIE_API_KEY", "")
    return cfg


def save(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean = dict(cfg)
    clean.pop("_mics", None)
    clean.pop("_has_key", None)
    clean.pop("key_hint", None)

    key = str(clean.pop("api_key", "") or "").strip()
    if key:
        token = dpapi.protect(key) if dpapi else ""
        if token:
            clean["api_key_enc"] = token
            clean.pop("api_key", None)
        else:
            clean["api_key"] = key
    else:
        clean.pop("api_key_enc", None)

    SETTINGS_PATH.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def notes_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return NOTES_PATH
