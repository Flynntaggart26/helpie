"""Helpie — voice assistant for Windows.

Run:  python helpie.py     (or double-click basla.bat)
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

import config  # noqa: E402
import shell  # noqa: E402
import updater  # noqa: E402
from server import App, free_port, serve  # noqa: E402

WINDOW_TITLE = "Helpie"
WIN_W, WIN_H = 1180, 780
TINY_W, TINY_H = 360, 180

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


# --------------------------------------------------------------------------- #
#  Window helpers
# --------------------------------------------------------------------------- #
def focus_window() -> bool:
    if shell.request("focus"):
        return True
    hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        return False
    ctypes.windll.user32.ShowWindow(hwnd, 9)  # restore
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    return True


def screen_size() -> tuple[int, int]:
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


def open_window(url: str) -> None:
    if shell.request("full"):
        return
    if os.environ.get("HELPIE_NO_BROWSER") == "1":
        return
    width, height = screen_size()
    x = max(0, (width - WIN_W) // 2)
    y = max(0, (height - WIN_H) // 2 - 20)
    profile = config.DATA_DIR / "browser"
    profile.mkdir(parents=True, exist_ok=True)

    executable = next((p for p in EDGE_PATHS if Path(p).exists()), None)
    if executable is None:
        executable = next((p for p in CHROME_PATHS if Path(p).exists()), None)

    if executable:
        subprocess.Popen([
            executable,
            f"--app={url}",
            f"--window-size={WIN_W},{WIN_H}",
            f"--window-position={x},{y}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--no-service-autorun",
            "--disable-notifications",
            "--disable-features=msEdgeSyncPromo,msEdgeSplitScreen,msEdgeSidebar",
        ])
    else:
        import webbrowser

        webbrowser.open(url)


def open_tiny_window(url: str) -> None:
    """Open a small floating window near the mouse cursor for wake-word interactions."""
    if shell.request("tiny"):
        return
    if os.environ.get("HELPIE_NO_BROWSER") == "1":
        return
    width, height = screen_size()
    # Position near mouse cursor (bottom-right of cursor)
    cursor_x, cursor_y = get_cursor_pos()
    x = min(cursor_x + 20, width - TINY_W - 20)
    y = min(cursor_y + 20, height - TINY_H - 20)
    profile = config.DATA_DIR / "browser"
    profile.mkdir(parents=True, exist_ok=True)

    executable = next((p for p in EDGE_PATHS if Path(p).exists()), None)
    if executable is None:
        executable = next((p for p in CHROME_PATHS if Path(p).exists()), None)

    if executable:
        subprocess.Popen([
            executable,
            f"--app={url}",
            f"--window-size={TINY_W},{TINY_H}",
            f"--window-position={x},{y}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--no-service-autorun",
            "--disable-notifications",
            "--disable-features=msEdgeSyncPromo,msEdgeSplitScreen,msEdgeSidebar",
        ])
    else:
        import webbrowser
        webbrowser.open(url)


def get_cursor_pos() -> tuple[int, int]:
    """Get current mouse cursor position."""
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# --------------------------------------------------------------------------- #
#  Single instance
# --------------------------------------------------------------------------- #
def running_port() -> int | None:
    if not config.PORT_PATH.exists():
        return None
    try:
        port = int(config.PORT_PATH.read_text().strip())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.2) as response:
            if response.status == 200:
                return port
    except Exception:
        return None
    return None


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def requested_port() -> int | None:
    """Port handed to us by the Tauri shell, so it knows where to connect."""
    raw = os.environ.get("HELPIE_PORT", "").strip()
    if not raw.isdigit():
        return None
    port = int(raw)
    return port if 0 < port < 65536 else None


def main() -> None:
    hidden = "--hidden" in sys.argv
    existing = running_port()
    if existing:
        if not hidden:
            if not focus_window():
                open_window(f"http://127.0.0.1:{existing}/")
        print(f"Helpie is already running on port {existing}.")
        return

    app = App()
    port = requested_port() or free_port()
    app.port = port  # Store port for wake word tiny window
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.PORT_PATH.write_text(str(port), encoding="utf-8")
    serve(app, port)

    url = f"http://127.0.0.1:{port}/"
    if not hidden and not shell.available():
        # Inside the Tauri shell the window already exists; the shell decides
        # whether to show it, so we must not force it open here.
        open_window(url)
    print(f"Helpie running at {url}  (version {updater.current_version()})")

    # Global hotkey: summon the desktop companion without opening full chat.
    push_to_talk_held = threading.Event()

    def hotkey() -> None:
        if push_to_talk_held.is_set():
            return
        push_to_talk_held.set()
        app.start_push_to_talk()
        if shell.available():
            if not shell.request("companion"):
                if not focus_window():
                    open_window(url)
        else:
            open_tiny_window(url)

    def hotkey_released(_event=None) -> None:
        if push_to_talk_held.is_set():
            push_to_talk_held.clear()
            app.stop_push_to_talk()

    try:
        import keyboard

        hotkey_combo = app.cfg.get("hotkey", "ctrl+h")
        keyboard.add_hotkey(hotkey_combo, hotkey, trigger_on_release=False)
        keyboard.on_release_key("h", hotkey_released)
        keyboard.on_release_key("ctrl", hotkey_released)
    except Exception:
        print("Global hotkey could not be registered.")

    # greeting + automatic listening
    def start_flow() -> None:
        if hidden:
            if app.cfg.get("check_updates", True):
                threading.Thread(target=silent_update_check, args=(app,), daemon=True).start()
            return
        time.sleep(2.5)
        greeting = app.brain.summary()
        app.bus.push({"type": "message", "role": "assistant", "text": greeting})
        app.history.append("assistant", greeting)
        app.speaker.say(greeting)
        app.speaker.wait_idle(25)
        if app.cfg.get("auto_listen", True) and not app._no_voice:
            app.listen_async("auto")

        if app.cfg.get("check_updates", True):
            threading.Thread(target=silent_update_check, args=(app,), daemon=True).start()

    threading.Thread(target=start_flow, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        app.shutdown()


def silent_update_check(app: App) -> None:
    result = updater.check()
    if result.get("available") and result.get("url"):
        app.bus.push({
            "type": "update",
            "version": result.get("latest"),
            "current": result.get("current"),
            "url": result.get("url"),
            "notes": result.get("notes", ""),
        })


if __name__ == "__main__":
    main()
