"""Settings load/save (the API key is encrypted with Windows DPAPI)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:  # The backend puts core/ on sys.path; this resolves to core/secrets.py.
    import secrets as dpapi
except Exception:  # pragma: no cover
    dpapi = None


def _app_dir() -> Path:
    """Where the bundled read-only assets (ui/, plugins/, VERSION) live."""
    if getattr(sys, "frozen", False):
        # PyInstaller onefile unpacks into _MEIPASS; onedir puts assets next to the exe.
        base = getattr(sys, "_MEIPASS", None)
        return Path(base) if base else Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    """Writable location for settings, history and the API key.

    Installed builds live under Program Files, which is read-only, so user data
    goes to %APPDATA%\\Helpie. A HELPIE_DATA_DIR override wins over everything.
    """
    override = os.environ.get("HELPIE_DATA_DIR", "").strip()
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "Helpie"
    return APP_DIR / "data"


APP_DIR = _app_dir()
DATA_DIR = _data_dir()
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
    "cloud_speech_consent": False,
    "cloud_tts_consent": False,
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

    legacy_plaintext = []
    for field in ("api_key", "openai_key", "wake_word_access_key"):
        encrypted = str(raw.get(f"{field}_enc") or "")
        plaintext = str(raw.get(field) or "")
        if encrypted:
            decrypted = dpapi.unprotect(encrypted) if dpapi else ""
            cfg[field] = decrypted
        elif plaintext:
            cfg[field] = plaintext
            legacy_plaintext.append(field)

    # Migrate old plaintext settings. If DPAPI is unavailable or fails, erase
    # the plaintext from disk and require the user to enter the key again.
    if legacy_plaintext:
        try:
            save(cfg)
        except (OSError, RuntimeError):
            for field in legacy_plaintext:
                cfg[field] = ""
                raw.pop(field, None)
            SETTINGS_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("HELPIE_API_KEY", "")
    return cfg


def save(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean = dict(cfg)
    clean.pop("_mics", None)
    clean.pop("_has_key", None)
    clean.pop("key_hint", None)

    for field in ("api_key", "openai_key", "wake_word_access_key"):
        key = str(clean.pop(field, "") or "").strip()
        encrypted_field = f"{field}_enc"
        if key:
            token = dpapi.protect(key) if dpapi else ""
            if not token:
                raise RuntimeError(f"Could not securely protect {field}; the key was not saved.")
            clean[encrypted_field] = token
        else:
            clean.pop(encrypted_field, None)

    SETTINGS_PATH.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def protect_secret(value: str) -> str:
    """Protect a credential with the current Windows user's DPAPI key."""
    if not value:
        return ""
    token = dpapi.protect(value) if dpapi else ""
    if not token:
        raise RuntimeError("Windows could not securely protect this credential; it was not saved.")
    return token


def unprotect_secret(token: str) -> str:
    """Decrypt a credential protected for the current Windows user."""
    return dpapi.unprotect(token) if token and dpapi else ""


def notes_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return NOTES_PATH
