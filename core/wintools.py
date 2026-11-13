"""Small Windows helpers that do not belong to a single feature."""
from __future__ import annotations

import subprocess

import config

CREATE_NO_WINDOW = 0x08000000


def profile_dir() -> str:
    return str(config.DATA_DIR / "browser")


def close_browser_window() -> None:
    """Close only the Edge/Chrome window that belongs to Helpie."""
    profile = profile_dir().replace("'", "''")
    script = (
        "$target = '" + profile + "'; "
        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe'\" "
        "-ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($target) } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, timeout=12, creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass
