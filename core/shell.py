"""Bridge between the Python backend and the Tauri shell.

When Helpie runs inside the Tauri desktop shell, window control (show the full
app, pop the companion, show the overlay, quit) is owned by Rust. The shell exposes a tiny
localhost control endpoint and passes its port to us through the
``HELPIE_CONTROL_PORT`` environment variable.

Everything here degrades to a no-op when Helpie runs the old way
(``python helpie.py`` opening an Edge/Chrome app window), so both modes work.
"""
from __future__ import annotations

import os
import urllib.request
import urllib.error
from pathlib import Path

try:  # imported from the app root in helpie.py, from core/ in server.py
    import config
except Exception:  # pragma: no cover
    config = None


def _read_port_file() -> str:
    if config is None:
        return ""
    try:
        return (Path(config.DATA_DIR) / "control_port.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def control_port() -> int | None:
    """Port of the Tauri control endpoint, or None when not running in the shell."""
    raw = os.environ.get("HELPIE_CONTROL_PORT", "").strip() or _read_port_file()
    if not raw:
        return None
    try:
        port = int(raw)
    except (TypeError, ValueError):
        return None
    return port if 0 < port < 65536 else None


def available() -> bool:
    """True when a Tauri shell is driving the windows."""
    return control_port() is not None or os.environ.get("HELPIE_NO_BROWSER") == "1"


def request(action: str, timeout: float = 2.5) -> bool:
    """Ask the shell to perform a window action (full, focus, companion, quit).

    Returns False if no shell is listening, so callers can fall back to opening
    a browser window themselves.
    """
    port = control_port()
    token = os.environ.get("HELPIE_CONTROL_TOKEN", "").strip()
    if port is None or not token:
        return False
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/{action}",
            headers={"X-Helpie-Control-Token": token},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 300
    except Exception:
        return False


def capture_one_frame(timeout: float = 300.0) -> tuple[bool, tuple[bytes, str] | None] | None:
    """Request one native WGC frame from the Tauri shell.

    ``None`` means no authenticated shell is configured, so the caller may use
    the legacy development capture path. ``(True, None)`` means the shell
    handled the request but capture was canceled or unavailable; callers must
    not fall back to a broader desktop grab in that case.
    """
    port = control_port()
    token = os.environ.get("HELPIE_CONTROL_TOKEN", "").strip()
    if port is None or not token:
        if os.environ.get("HELPIE_NO_BROWSER") == "1":
            return True, None
        return None

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/capture",
        data=b"",
        headers={"X-Helpie-Control-Token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status == 204:
                return True, None
            if response.status != 200 or response.headers.get_content_type() != "image/png":
                return True, None
            image = response.read(128 * 1024 * 1024 + 1)
            if len(image) > 128 * 1024 * 1024 or not image.startswith(b"\x89PNG\r\n\x1a\n"):
                return True, None
            target = response.headers.get("X-Helpie-Capture-Target", "")[:200]
            return True, (image, target)
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return True, None
        return True, None
    except Exception:
        # The shell was configured for this run; fail closed instead of taking
        # an unconsented Pillow desktop screenshot after a transport failure.
        return True, None
