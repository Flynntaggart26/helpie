"""Start Helpie with Windows (HKCU Run key)."""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

import config

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Helpie"


def command() -> str:
    python = Path(sys.executable)
    windowed = python.with_name("pythonw.exe")
    executable = windowed if windowed.exists() else python
    script = config.APP_DIR / "helpie.py"
    return f'"{executable}" "{script}" --hidden'


def enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except OSError:
        return False


def set_enabled(on: bool) -> bool:
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
