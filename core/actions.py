"""Things Helpie can do on your Windows machine."""
from __future__ import annotations

import ctypes
import datetime as dt
import os
import re
import shutil
import subprocess
import threading
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Optional

import audit
import clipboard
import config
import reminders

CREATE_NO_WINDOW = 0x08000000


def _audit(action: str, detail: str = "", source: str = "action") -> None:
    """Record a side effect for the activity log. Never raises."""
    try:
        audit.log(action, detail, source=source)
    except Exception:
        pass

# --------------------------------------------------------------------------- #
#  Apps and sites
# --------------------------------------------------------------------------- #
APPS: dict[str, dict] = {
    "chrome": {"aliases": ["chrome", "google chrome", "browser", "tarayıcı", "krom"], "run": "chrome", "proc": "chrome.exe"},
    "edge": {"aliases": ["edge", "microsoft edge"], "run": "msedge", "proc": "msedge.exe"},
    "firefox": {"aliases": ["firefox"], "run": "firefox", "proc": "firefox.exe"},
    "spotify": {"aliases": ["spotify", "music app"], "run": "spotify", "proc": "Spotify.exe"},
    "notepad": {"aliases": ["notepad", "note pad", "not defteri"], "run": "notepad", "proc": "notepad.exe"},
    "calc": {"aliases": ["calculator", "calc", "hesap makinesi", "hesap makinası"], "run": "calc", "proc": "CalculatorApp.exe"},
    "explorer": {"aliases": ["file explorer", "explorer", "files", "dosya gezgini", "gezgin"], "run": "explorer", "proc": "explorer.exe"},
    "code": {"aliases": ["vs code", "vscode", "visual studio code", "code editor", "kod editörü"], "run": "code", "proc": "Code.exe"},
    "word": {"aliases": ["word", "microsoft word"], "run": "winword", "proc": "WINWORD.EXE"},
    "excel": {"aliases": ["excel", "microsoft excel"], "run": "excel", "proc": "EXCEL.EXE"},
    "powerpoint": {"aliases": ["powerpoint", "slides"], "run": "powerpnt", "proc": "POWERPNT.EXE"},
    "whatsapp": {"aliases": ["whatsapp"], "run": "whatsapp", "proc": "WhatsApp.exe"},
    "discord": {"aliases": ["discord"], "run": "discord", "proc": "Discord.exe"},
    "steam": {"aliases": ["steam"], "run": "steam", "proc": "steam.exe"},
    "telegram": {"aliases": ["telegram"], "run": "telegram", "proc": "Telegram.exe"},
    "terminal": {"aliases": ["terminal", "powershell", "command prompt", "cmd"], "run": "wt", "proc": "WindowsTerminal.exe"},
    "settings": {"aliases": ["settings", "ayarlar"], "run": "ms-settings:", "proc": None},
    "paint": {"aliases": ["paint", "boya"], "run": "mspaint", "proc": "mspaint.exe"},
    "snipping": {"aliases": ["snipping tool", "screen clip", "ekran alıntısı"], "run": "ms-screenclip:", "proc": None},
    "taskmgr": {"aliases": ["task manager", "görev yöneticisi"], "run": "taskmgr", "proc": "Taskmgr.exe"},
    "photos": {"aliases": ["photos", "gallery", "fotoğraflar"], "run": "ms-photos:", "proc": None},
    "store": {"aliases": ["store", "microsoft store", "mağaza"], "run": "ms-windows-store:", "proc": None},
    "camera": {"aliases": ["camera", "kamera"], "run": "microsoft.windows.camera:", "proc": None},
    "clock": {"aliases": ["alarm", "clock", "saat uygulaması"], "run": "ms-clock:", "proc": None},
    "mail": {"aliases": ["mail", "outlook"], "run": "outlook", "proc": "OUTLOOK.EXE"},
    "obs": {"aliases": ["obs"], "run": "obs64", "proc": "obs64.exe"},
    "vlc": {"aliases": ["vlc", "video player"], "run": "vlc", "proc": "vlc.exe"},
}

SITES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://twitter.com",
    "facebook": "https://www.facebook.com",
    "github": "https://github.com",
    "drive": "https://drive.google.com",
    "netflix": "https://www.netflix.com",
    "chatgpt": "https://chat.openai.com",
    "gemini": "https://gemini.google.com",
    "maps": "https://maps.google.com",
    "translate": "https://translate.google.com",
    "notion": "https://www.notion.so",
    "linkedin": "https://www.linkedin.com",
    "twitch": "https://www.twitch.tv",
    "reddit": "https://www.reddit.com",
    "stack overflow": "https://stackoverflow.com",
}

_APP_LOOKUP: list[tuple[str, str]] = []
for _key, _info in APPS.items():
    for _alias in _info["aliases"]:
        _APP_LOOKUP.append((_alias, _key))
_APP_LOOKUP.sort(key=lambda item: len(item[0]), reverse=True)

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# --------------------------------------------------------------------------- #
#  Low level helpers
# --------------------------------------------------------------------------- #
def _run(cmd: str | list[str], shell: bool = False) -> None:
    subprocess.Popen(cmd, shell=shell, creationflags=CREATE_NO_WINDOW,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _powershell(script: str, timeout: float = 20.0) -> str:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _key(vk: int, times: int = 1) -> None:
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.03)


VK_VOLUME_UP, VK_VOLUME_DOWN, VK_VOLUME_MUTE = 0xAF, 0xAE, 0xAD
VK_MEDIA_NEXT, VK_MEDIA_PREV, VK_MEDIA_PLAY = 0xB0, 0xB1, 0xB3


# --------------------------------------------------------------------------- #
#  Quiet launching (open apps without yanking them in front of you)
# --------------------------------------------------------------------------- #
BACKGROUND_APPS = True
_SCREEN_CONTEXT_CONSENT = False
SW_SHOWMINNOACTIVE = 7
SW_MINIMIZE = 6
BROWSER_PROCESSES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
                     "opera.exe", "vivaldi.exe", "iexplore.exe"}

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_shell32 = ctypes.windll.shell32

_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_shell32.ShellExecuteW.restype = wintypes.HINSTANCE
_shell32.ShellExecuteW.argtypes = [
    wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPCWSTR, ctypes.c_int,
]

_ENUM_WINDOWS = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def set_background_mode(enabled: bool) -> None:
    """Turn the 'open apps in the background' behaviour on or off at runtime."""
    global BACKGROUND_APPS
    BACKGROUND_APPS = bool(enabled)


def set_screen_context_consent(enabled: bool) -> None:
    """Turn screen context (AI screen reading) on or off at runtime.

    When off, capture_screen() refuses to grab the screen so no plugin or
    internal path can read the user's screen without consent.
    """
    global _SCREEN_CONTEXT_CONSENT
    _SCREEN_CONTEXT_CONSENT = bool(enabled)


def _foreground_hwnd() -> int:
    try:
        return int(_user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def _visible_hwnds() -> set[int]:
    found: set[int] = set()

    def _callback(hwnd, _lparam):
        if _user32.IsWindowVisible(hwnd):
            found.add(int(hwnd))
        return True

    try:
        _user32.EnumWindows(_ENUM_WINDOWS(_callback), 0)
    except Exception:
        pass
    return found


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    try:
        _user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    except Exception:
        return 0
    return int(pid.value)


def _process_name(pid: int) -> str:
    if not pid:
        return ""
    handle = _kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value).lower()
    except Exception:
        pass
    finally:
        _kernel32.CloseHandle(handle)
    return ""


def _shell_open(target: str, params: Optional[str] = None, show: int = SW_SHOWMINNOACTIVE) -> bool:
    try:
        result = _shell32.ShellExecuteW(None, "open", target, params, None, show)
        return int(result or 0) > 32
    except Exception:
        return False


def _minimize(hwnd: int) -> None:
    try:
        _user32.ShowWindow(wintypes.HWND(hwnd), SW_MINIMIZE)
    except Exception:
        pass


def _restore(hwnd: int) -> None:
    if not hwnd:
        return
    try:
        _user32.SetForegroundWindow(wintypes.HWND(hwnd))
    except Exception:
        pass


def _watch_launch(process_names: set[str], before: set[int], previous: int,
                  timeout: float = 8.0) -> None:
    """Keep a freshly launched app out of the foreground.

    New windows that belong to the launched process are minimised, and if it still
    grabs focus the previously focused window is put back in front.
    """
    names = {name.lower() for name in process_names if name}
    end = time.time() + timeout
    while time.time() < end:
        current = _foreground_hwnd()
        if current and current != previous:
            name = _process_name(_window_pid(current))
            if name in names or current not in before:
                if current not in before:
                    _minimize(current)
                _restore(previous)

        for hwnd in _visible_hwnds() - before:
            if _process_name(_window_pid(hwnd)) in names:
                _minimize(hwnd)
        time.sleep(0.2)


def _launch(target: str, process_names: Optional[list[str]] = None) -> bool:
    """Start a program or URI. Returns True when it was started successfully."""
    if not BACKGROUND_APPS:
        if _shell_open(target, show=5):  # SW_SHOW
            return True
        return False

    previous = _foreground_hwnd()
    before = _visible_hwnds()
    started = _shell_open(target)
    if not started:
        return False
    names = set(process_names or [])
    if re.match(r"(?i)^(https?://|www\.)", target):
        names |= BROWSER_PROCESSES
    watcher = threading.Thread(
        target=_watch_launch,
        args=(names, before, previous),
        daemon=True,
        name="helpie-launch-watch",
    )
    watcher.start()
    return True


# --------------------------------------------------------------------------- #
#  Apps
# --------------------------------------------------------------------------- #
def resolve_app(text: str) -> Optional[str]:
    t = text.lower().strip()
    for alias, key in _APP_LOOKUP:
        if re.search(rf"(^|\s){re.escape(alias)}($|\s|['’]|s$)", t) or alias in t:
            return key
    return None


def open_app(name: str) -> str:
    key = resolve_app(name)
    if key:
        target = APPS[key]["run"]
        proc = APPS[key].get("proc")
        try:
            if _launch(target, [proc] if proc else []):
                _audit("Opened app", key)
                return f"Opening {key} in the background." if BACKGROUND_APPS else f"Opening {key}."
        except Exception:
            pass
        return f"Could not open {key}."
    cleaned = re.sub(r"(app|application|program|uygulamasını|programını)\s*$", "", name.strip()).strip()
    cleaned = re.sub(r"['’]s?$", "", cleaned).strip()
    if not cleaned:
        return "Which app should I open?"
    try:
        if not _launch(cleaned):
            previous = _foreground_hwnd()
            before = _visible_hwnds()
            subprocess.Popen(["cmd", "/c", "start", "", cleaned], creationflags=CREATE_NO_WINDOW)
            if BACKGROUND_APPS:
                threading.Thread(target=_watch_launch, args=(set(), before, previous),
                                 daemon=True, name="helpie-launch-watch").start()
        _audit("Opened app", cleaned)
        return f"Opening {cleaned} in the background." if BACKGROUND_APPS else f"Opening {cleaned}."
    except Exception:
        return f"I could not find an app called {cleaned}."

def close_app(name: str) -> str:
    key = resolve_app(name)
    if not key or not APPS[key]["proc"]:
        return f"I could not find {name} running."
    subprocess.Popen(["taskkill", "/IM", APPS[key]["proc"], "/F"],
                     creationflags=CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _audit("Closed app", key)
    return f"Closed {key}."


# --------------------------------------------------------------------------- #
#  Sound, brightness, media
# --------------------------------------------------------------------------- #
def get_volume() -> Optional[float]:
    try:
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        device = AudioUtilities.GetSpeakers()
        interface = cast(device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
                         POINTER(IAudioEndpointVolume))
        return float(interface.GetMasterVolumeLevelScalar()) * 100.0
    except Exception:
        return None


def set_volume(percent: float) -> str:
    percent = max(0.0, min(100.0, percent))
    try:
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        device = AudioUtilities.GetSpeakers()
        interface = cast(device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
                         POINTER(IAudioEndpointVolume))
        interface.SetMasterVolumeLevelScalar(percent / 100.0, None)
        _audit("Set volume", f"{round(percent)}%")
        return f"Volume set to {round(percent)} percent."
    except Exception:
        current = get_volume()
        if current is None:
            steps = max(1, int(percent / 2))
            _key(VK_VOLUME_UP, min(steps, 50))
            _audit("Set volume", f"~{round(percent)}%")
            return f"Volume turned up towards {round(percent)} percent."
        diff = int(round((percent - current) / 2))
        _key(VK_VOLUME_UP if diff > 0 else VK_VOLUME_DOWN, min(abs(diff), 25))
        _audit("Set volume", f"~{round(percent)}%")
        return f"Volume set to about {round(percent)} percent."


def volume(direction: str = "up", step: int = 4) -> str:
    if direction == "mute":
        _key(VK_VOLUME_MUTE)
        _audit("Muted the sound")
        return "Muted."
    _key(VK_VOLUME_UP if direction == "up" else VK_VOLUME_DOWN, step)
    current = get_volume()
    word = "up" if direction == "up" else "down"
    _audit("Changed volume", word)
    if current is None:
        return f"Volume turned {word}."
    return f"Volume turned {word}. It is now {round(current)} percent."


def media(action: str) -> str:
    if action == "play":
        _key(VK_MEDIA_PLAY)
        _audit("Media control", "play")
        return "Playing."
    if action == "next":
        _key(VK_MEDIA_NEXT)
        _audit("Media control", "next track")
        return "Next track."
    if action == "prev":
        _key(VK_MEDIA_PREV)
        _audit("Media control", "previous track")
        return "Previous track."
    return "I did not catch that media command."


def get_brightness() -> Optional[int]:
    out = _powershell(
        "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness "
        "-ErrorAction SilentlyContinue).CurrentBrightness"
    )
    try:
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def set_brightness(percent: int) -> str:
    percent = max(0, min(100, int(percent)))
    script = (
        "$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods "
        "-ErrorAction SilentlyContinue; "
        "if ($m) { $m | Invoke-CimMethod -MethodName WmiSetBrightness "
        f"-Arguments @{{Brightness=[byte]{percent}}} | Out-Null; 'ok' }} else {{ 'no' }}"
    )
    if _powershell(script).strip().endswith("ok"):
        _audit("Set brightness", f"{percent}%")
        return f"Brightness set to {percent} percent."
    return "This display does not support brightness control (common on desktop monitors)."


def brightness(direction: str, step: int = 10) -> str:
    current = get_brightness()
    if current is None:
        return "This display does not support brightness control."
    return set_brightness(current + step if direction == "up" else current - step)


# --------------------------------------------------------------------------- #
#  Web
# --------------------------------------------------------------------------- #
def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not _launch(url):
        webbrowser.open(url)
    _audit("Opened link", url)
    return "Opened it" + (" in the background." if BACKGROUND_APPS else ".")


def web_search(query: str, engine: str = "google") -> str:
    from urllib.parse import quote_plus

    suffix = " in the background" if BACKGROUND_APPS else ""
    if engine == "youtube":
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        message = f"Searching YouTube for {query}{suffix}."
    else:
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        message = f"Searching the web for {query}{suffix}."
    if not _launch(url):
        webbrowser.open(url)
    _audit("Web search", f"{query} ({engine})")
    return message


def open_site(name: str) -> str:
    key = name.lower().strip()
    url = SITES.get(key)
    if not url:
        for site, link in SITES.items():
            if site in key or key in site:
                url, key = link, site
                break
    if not url:
        return f"I do not know the site {name}."
    if not _launch(url):
        webbrowser.open(url)
    _audit("Opened site", key)
    return f"Opening {key}" + (" in the background." if BACKGROUND_APPS else ".")


def weather(city: str = "", timeout: float = 10.0) -> str:
    import requests

    try:
        place = city.strip()
        r = requests.get(f"https://wttr.in/{place}?format=%l:+%C,+%t&m",
                         timeout=timeout, headers={"User-Agent": "curl/8"})
        text = (r.text or "").strip()
        if not text or "<html" in text.lower():
            return "I could not reach the weather service."
        return text.replace("+", "")
    except Exception:
        return "I could not reach the weather service. Check your connection."


# --------------------------------------------------------------------------- #
#  Notes
# --------------------------------------------------------------------------- #
def add_note(text: str) -> str:
    text = text.strip()
    if not text:
        return "What should I write down?"
    path = config.notes_path()
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"- [{stamp}] {text}\n")
    _audit("Saved a note", text)
    return "Saved to your notes."


def notes_list() -> list[dict]:
    path = config.notes_path()
    if not path.exists():
        return []
    items: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"- \[(.*?)\] (.*)", line)
        if match:
            items.append({"time": match.group(1), "text": match.group(2)})
        else:
            items.append({"time": "", "text": line.lstrip("- ").strip()})
    return items


def read_notes(limit: int = 5) -> str:
    items = notes_list()
    if not items:
        return "You have no notes yet."
    recent = items[-limit:]
    return "Latest notes: " + " | ".join(f"{item['text']}" for item in recent)


def clear_notes() -> str:
    config.notes_path().write_text("", encoding="utf-8")
    _audit("Cleared all notes")
    return "All notes cleared."


# --------------------------------------------------------------------------- #
#  Screen and power
# --------------------------------------------------------------------------- #
def screenshot() -> str:
    from PIL import ImageGrab

    folder = Path.home() / "Pictures" / "Helpie"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"shot_{dt.datetime.now():%Y%m%d_%H%M%S}.png"
    ImageGrab.grab(all_screens=True).save(path)
    _audit("Took a screenshot", path.name)
    return f"Screenshot saved as {path.name}."


def capture_screen(max_width: int = 1600) -> Optional[bytes]:
    """Grab the current screen as a downscaled PNG (for the vision model).

    Refuses to capture when screen context consent is off, so no plugin or
    internal path can read the user's screen without consent.
    """
    if not _SCREEN_CONTEXT_CONSENT:
        return None
    try:
        import io

        from PIL import ImageGrab

        image = ImageGrab.grab(all_screens=True)
        if image.width > max_width:
            height = max(1, int(image.height * max_width / image.width))
            image = image.resize((max_width, height))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    except Exception:
        return None


def briefing(city: str = "") -> str:
    """A short spoken overview: time, weather, battery, reminders and recent notes."""
    now = dt.datetime.now()
    if now.hour < 12:
        hello = "Good morning"
    elif now.hour < 18:
        hello = "Good afternoon"
    else:
        hello = "Good evening"
    parts = [f"{hello}. It is {now.hour:02d}:{now.minute:02d} on "
             f"{DAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]}."]

    forecast = weather(city)
    if forecast and "could not" not in forecast.lower():
        parts.append(f"Weather: {forecast}.")

    power = battery()
    if "percent" in power:
        parts.append(power)

    upcoming = reminders.store.list()[:3]
    if upcoming:
        items = []
        for item in upcoming:
            when = dt.datetime.fromisoformat(item["due"])
            items.append(f"{when:%H:%M} {item['text']}")
        parts.append("Next reminders: " + ", ".join(items) + ".")

    recent_notes = notes_list()[-2:]
    if recent_notes:
        parts.append("Recent note: " + recent_notes[-1]["text"] + ".")

    items = reminders.store.list()
    parts.append(f"You have {len(items)} reminder{'s' if len(items) != 1 else ''} saved." if items
                 else "You have no reminders waiting.")
    return " ".join(parts)


def lock_screen() -> str:
    _audit("Locked the screen")
    ctypes.windll.user32.LockWorkStation()
    return "Locking the screen."


def sleep_pc() -> str:
    _audit("Put the PC to sleep")
    _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return "Putting the computer to sleep."


def shutdown_pc(restart: bool = False) -> str:
    _audit("Restarting the PC" if restart else "Shutting down the PC")
    _run(["shutdown", "/r" if restart else "/s", "/t", "5"])
    return "Restarting in 5 seconds." if restart else "Shutting down in 5 seconds."


def cancel_shutdown() -> str:
    _run(["shutdown", "/a"])
    return "Shutdown cancelled."


def empty_recycle_bin() -> str:
    _audit("Emptied the recycle bin")
    _powershell("Clear-RecycleBin -Force -ErrorAction SilentlyContinue")
    return "Recycle bin emptied."


def battery() -> str:
    class STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", wintypes.BYTE),
            ("BatteryFlag", wintypes.BYTE),
            ("BatteryLifePercent", wintypes.BYTE),
            ("Reserved1", wintypes.BYTE),
            ("BatteryLifeTime", wintypes.DWORD),
            ("BatteryFullLifeTime", wintypes.DWORD),
        ]

    status = STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return "I could not read the battery status."
    if status.BatteryLifePercent in (255, 0):
        return "This computer has no battery. It is running on wall power."
    state = "plugged in" if status.ACLineStatus == 1 else "on battery"
    return f"Battery is at {status.BatteryLifePercent} percent, {state}."


def system_info() -> str:
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.4)
        ram = psutil.virtual_memory()
        return f"CPU at {cpu:.0f} percent, RAM at {ram.percent:.0f} percent."
    except Exception:
        return "I need psutil installed to read system stats."


# --------------------------------------------------------------------------- #
#  Keyboard
# --------------------------------------------------------------------------- #
class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def type_text(text: str) -> str:
    if not text:
        return "What should I type?"
    KEYEVENTF_UNICODE, KEYEVENTF_KEYUP = 0x0004, 0x0002
    events = []
    for char in text:
        for flag in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            event = _INPUT(type=1)
            event.u.ki = _KEYBDINPUT(0, ord(char), flag, 0, None)
            events.append(event)
    if not events:
        return "Nothing to type."
    array = (_INPUT * len(events))(*events)
    time.sleep(0.35)
    if ctypes.windll.user32.SendInput(len(events), array, ctypes.sizeof(_INPUT)):
        _audit("Typed text", text)
        return "Typed it."
    return "I could not type. Make sure a text field is focused."


def press_key(keys: str) -> str:
    vk_map = {"win": 0x5B, "d": 0x44, "tab": 0x09, "alt": 0x12, "enter": 0x0D,
              "esc": 0x1B, "ctrl": 0x11, "shift": 0x10}
    parts = [p.strip().lower() for p in keys.split("+") if p.strip()]
    vks = [vk_map.get(p, ord(p.upper()) if len(p) == 1 else None) for p in parts]
    if any(v is None for v in vks):
        return "I do not know that shortcut."
    for vk in vks:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    return "Done."


# --------------------------------------------------------------------------- #
#  Files
# --------------------------------------------------------------------------- #
def find_file(query: str, suffixes: Optional[set[str]] = None) -> Optional[Path]:
    query = query.lower().strip()
    if not query:
        return None
    roots = [Path.home() / "Desktop", Path.home() / "Documents",
             Path.home() / "Downloads", Path.home() / "OneDrive" / "Desktop", Path.home()]
    best: tuple[int, Path] | None = None
    for root in roots:
        if not root.exists():
            continue
        for walk_root, dirs, files in os.walk(root):
            if str(walk_root).count(os.sep) - str(root).count(os.sep) > 2:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in
                       {"AppData", "node_modules", ".git", "__pycache__", ".venv", "venv", "$RECYCLE.BIN"}]
            for filename in files:
                if suffixes and Path(filename).suffix.lower() not in suffixes:
                    continue
                name = filename.lower()
                if query in name:
                    score = len(query) * 2
                else:
                    tokens = [t for t in re.split(r"\W+", query)
                              if len(t) > 2 and t not in
                              {"the", "file", "files", "document", "documents",
                               "dosya", "dosyayı", "belge", "belgeyi"}]
                    score = 0
                    for token in tokens:
                        if token not in name:
                            continue
                        whole = re.search(rf"(?:^|[\s._\-]){re.escape(token)}(?:[\s._\-]|$)", name)
                        if len(token) >= 4 or whole:
                            score += len(token) * max(1, len(tokens))
                if score and (best is None or score > best[0]):
                    best = (score, Path(walk_root) / filename)
    return best[1] if best else None


def open_file(query: str) -> str:
    path = find_file(query)
    if not path:
        return f"I could not find a file called {query}."
    os.startfile(str(path))
    _audit("Opened a file", path.name, "files")
    return f"Opening {path.name}."


def open_folder(name: str = "") -> str:
    key = name.lower()
    mapping = {
        "desktop": Path.home() / "Desktop",
        "downloads": Path.home() / "Downloads",
        "documents": Path.home() / "Documents",
        "pictures": Path.home() / "Pictures",
        "music": Path.home() / "Music",
        "videos": Path.home() / "Videos",
    }
    for alias, path in mapping.items():
        if alias in key:
            os.startfile(str(path))
            _audit("Opened a folder", alias, "files")
            return f"Opening {alias}."
    os.startfile(str(Path.home()))
    _audit("Opened a folder", "home", "files")
    return "Opening your home folder."


# --------------------------------------------------------------------------- #
#  File organizer
# --------------------------------------------------------------------------- #
FILE_CATEGORIES: dict[str, set[str]] = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".svg", ".ico", ".heic", ".avif"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".tex", ".epub"},
    "Spreadsheets": {".xls", ".xlsx", ".csv", ".ods", ".tsv"},
    "Presentations": {".ppt", ".pptx", ".odp", ".key"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"},
    "Video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".cs", ".java", ".cpp", ".c", ".h", ".go", ".rs", ".php", ".rb", ".sh", ".sql"},
    "Executables": {".exe", ".msi", ".app", ".deb", ".rpm", ".apk", ".jar", ".bat", ".cmd", ".ps1"},
    "Fonts": {".ttf", ".otf", ".woff", ".woff2", ".eot"},
    "3D": {".stl", ".obj", ".fbx", ".blend", ".gltf", ".glb", ".dae", ".ply"},
}

DEFAULT_FOLDERS = [
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Documents",
    Path.home() / "OneDrive" / "Desktop",
]


def _category_for(suffix: str) -> str:
    suffix = suffix.lower()
    for cat, exts in FILE_CATEGORIES.items():
        if suffix in exts:
            return cat
    return "Other"


def _safe_move(src: Path, dst_dir: Path, dry_run: bool = False) -> tuple[bool, str]:
    """Move src into dst_dir, avoiding collisions. Returns (moved, destination_name)."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if not dst.exists():
        if not dry_run:
            try:
                shutil.move(str(src), str(dst))
            except Exception as e:
                return False, f"error: {e}"
        return True, dst.name
    # collision: add counter
    stem, ext = src.stem, src.suffix
    counter = 1
    while True:
        new_name = f"{stem} ({counter}){ext}"
        dst = dst_dir / new_name
        if not dst.exists():
            if not dry_run:
                try:
                    shutil.move(str(src), str(dst))
                except Exception as e:
                    return False, f"error: {e}"
            return True, new_name
        counter += 1
        if counter > 999:
            return False, "too many collisions"


def organize_folder(folder: Path, by: str = "type", dry_run: bool = False) -> dict:
    """Organize files in folder by type or date. Returns stats dict."""
    if not folder.exists() or not folder.is_dir():
        return {"error": f"Folder not found: {folder}"}
    if by not in ("type", "date"):
        return {"error": "by must be 'type' or 'date'"}

    moved = 0
    skipped = 0
    errors = 0
    details: list[str] = []

    for item in folder.iterdir():
        if not item.is_file():
            continue
        if item.name.startswith("."):
            continue
        if by == "type":
            cat = _category_for(item.suffix)
            target_dir = folder / cat
        else:  # date
            try:
                mtime = dt.datetime.fromtimestamp(item.stat().st_mtime)
                target_dir = folder / mtime.strftime("%Y-%m")
            except Exception:
                target_dir = folder / "Unknown-Date"
        ok, msg = _safe_move(item, target_dir, dry_run)
        if ok:
            moved += 1
            details.append(f"  {item.name} → {target_dir.name}/{msg}")
        else:
            errors += 1
            details.append(f"  {item.name} → FAILED: {msg}")

    _audit("Organized a folder",
           f"{folder.name} by {by} · {moved} moved{' (preview)' if dry_run else ''}", "files")
    return {
        "folder": str(folder),
        "by": by,
        "dry_run": dry_run,
        "moved": moved,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }


def organize_all(by: str = "type", dry_run: bool = False) -> list[dict]:
    results = []
    for folder in DEFAULT_FOLDERS:
        if folder.exists():
            results.append(organize_folder(folder, by, dry_run))
    return results


def find_duplicates(folder: Path) -> list[list[Path]]:
    """Return groups of duplicate files (same size + hash) under folder."""
    import hashlib
    by_size: dict[int, list[Path]] = {}
    for item in folder.rglob("*"):
        if not item.is_file():
            continue
        try:
            size = item.stat().st_size
        except OSError:
            continue
        by_size.setdefault(size, []).append(item)

    dup_groups: list[list[Path]] = []
    for size, files in by_size.items():
        if len(files) < 2:
            continue
        by_hash: dict[str, list[Path]] = {}
        for f in files:
            try:
                h = hashlib.md5(f.read_bytes()).hexdigest()
            except Exception:
                continue
            by_hash.setdefault(h, []).append(f)
        for group in by_hash.values():
            if len(group) > 1:
                dup_groups.append(group)
    return dup_groups


def remove_duplicates(folder: Path, dry_run: bool = False) -> dict:
    groups = find_duplicates(folder)
    removed = 0
    freed = 0
    details: list[str] = []
    for group in groups:
        # keep the first (by name), remove rest
        keeper = min(group, key=lambda p: p.name)
        for dup in group:
            if dup == keeper:
                continue
            try:
                size = dup.stat().st_size
                if not dry_run:
                    dup.unlink()
                removed += 1
                freed += size
                details.append(f"Removed duplicate: {dup.relative_to(folder)} (kept {keeper.relative_to(folder)})")
            except Exception as e:
                details.append(f"Failed to remove {dup}: {e}")
    _audit("Removed duplicate files",
           f"{folder.name} · {removed} removed{' (preview)' if dry_run else ''}", "files")
    return {"folder": str(folder), "groups": len(groups), "removed": removed, "freed_bytes": freed, "dry_run": dry_run, "details": details}


def clean_empty_folders(folder: Path, dry_run: bool = False) -> dict:
    removed = 0
    details: list[str] = []
    for root, dirs, files in os.walk(folder, topdown=False):
        for d in dirs:
            dir_path = Path(root) / d
            try:
                if not any(dir_path.iterdir()):
                    if not dry_run:
                        dir_path.rmdir()
                    removed += 1
                    details.append(f"Removed empty folder: {dir_path.relative_to(folder)}")
            except Exception as e:
                details.append(f"Failed to remove {dir_path}: {e}")
    _audit("Cleaned empty folders", f"{folder.name} · {removed} removed{' (preview)' if dry_run else ''}", "files")
    return {"folder": str(folder), "removed": removed, "dry_run": dry_run, "details": details}


# --------------------------------------------------------------------------- #
#  Math, time, timers
# --------------------------------------------------------------------------- #
def calculate(expression: str) -> str:
    import ast
    import math
    import operator

    expr = expression.lower().replace(",", ".")

    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s*(?:of)\s*(\d+(?:\.\d+)?)", expr)
    if percent_match:
        rate, base = float(percent_match.group(1)), float(percent_match.group(2))
        value = base * rate / 100
        return f"Result: {int(value) if float(value).is_integer() else round(value, 4)}"

    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:'?(?:in|ın|un|ün|nin|nın))?\s*yüzde\s*(\d+(?:\.\d+)?)", expr)
    if percent_match:
        base, rate = float(percent_match.group(1)), float(percent_match.group(2))
        value = base * rate / 100
        return f"Result: {int(value) if float(value).is_integer() else round(value, 4)}"

    sqrt_match = re.search(r"(?:square root of|karekök)\s*(?:al|bul)?\s*(\d+(?:\.\d+)?)", expr)
    if sqrt_match:
        value = math.sqrt(float(sqrt_match.group(1)))
        return f"Result: {int(value) if float(value).is_integer() else round(value, 4)}"

    replacements = {
        "divided by": "/", "multiplied by": "*", "times": "*", "plus": "+",
        "minus": "-", "to the power of": "**", "squared": "**2", "percent of": "%",
        "çarpı": "*", "kere": "*", "bölü": "/", "artı": "+", "eksi": "-",
        "üzeri": "**", "böl": "/", "x": "*",
    }
    for word, symbol in replacements.items():
        expr = expr.replace(word, symbol)

    expr = re.sub(r"[^\d+\-*/().\s%]", " ", expr)
    expr = re.sub(r"\s+", " ", expr).strip()
    if not expr or not re.search(r"\d", expr):
        return "I could not find a calculation in that."

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp):
            ops = {ast.Add: operator.add, ast.Sub: operator.sub,
                   ast.Mult: operator.mul, ast.Div: operator.truediv,
                   ast.Mod: operator.mod, ast.Pow: operator.pow}
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return -_eval(node.operand) if isinstance(node.op, ast.USub) else _eval(node.operand)
        raise ValueError("unsupported")

    try:
        value = _eval(ast.parse(expr, mode="eval"))
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        text = f"{value:.4f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
        return f"Result: {text}"
    except Exception:
        return "I could not calculate that."


def now_time() -> str:
    now = dt.datetime.now()
    return f"It is {now.hour:02d}:{now.minute:02d}."


def now_date() -> str:
    now = dt.datetime.now()
    return f"Today is {DAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} {now.year}."


def set_timer(seconds: float, label: str, on_fire: Callable[[str], None]) -> str:
    seconds = max(1.0, float(seconds))
    text = (label or "").strip() or "your timer is done"
    if reminders.store.on_fire is None:
        reminders.store.on_fire = lambda item: on_fire(f"Reminder: {item['text']}")
    reminders.store.start()
    reminders.store.add_in(seconds, text)
    span = f"{int(seconds)} seconds" if seconds < 60 else f"{seconds / 60:.0f} minutes"
    _audit("Set a timer", f"{span} · {text}")
    return f"Timer set for {span}."


# --------------------------------------------------------------------------- #
#  Reminders
# --------------------------------------------------------------------------- #
def add_reminder(text: str, due: dt.datetime, repeat: str = "none") -> str:
    item = reminders.store.add(text, due, repeat)
    when = dt.datetime.fromisoformat(item["due"])
    pretty = when.strftime("%H:%M") if when.date() == dt.date.today() else when.strftime("%a %d %b, %H:%M")
    _audit("Added a reminder", f"{pretty} · {item['text']}")
    if repeat == "daily":
        return f"Okay. I will remind you every day at {pretty[-5:]} to {item['text']}."
    if repeat == "weekdays":
        return f"Okay. I will remind you on weekdays at {pretty[-5:]} to {item['text']}."
    if repeat == "weekly":
        return f"Okay. I will remind you every week on {pretty} to {item['text']}."
    return f"Okay. I will remind you at {pretty} to {item['text']}."


def read_reminders() -> str:
    items = reminders.store.list()
    if not items:
        return "You have no reminders."
    parts = []
    for item in items[:6]:
        when = dt.datetime.fromisoformat(item["due"])
        stamp = when.strftime("%a %H:%M")
        repeat = "" if item["repeat"] == "none" else f" ({item['repeat']})"
        parts.append(f"{stamp}{repeat}: {item['text']}")
    return "Reminders: " + " | ".join(parts) + "."


def clear_reminders() -> str:
    count = reminders.store.clear()
    return f"Cleared {count} reminder{'s' if count != 1 else ''}."


# --------------------------------------------------------------------------- #
#  Clipboard
# --------------------------------------------------------------------------- #
def read_clipboard() -> str:
    text = clipboard.get_text()
    if not text.strip():
        return "The clipboard is empty."
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) > 400:
        clean = clean[:400] + "…"
    return f"The clipboard says: {clean}"


def write_clipboard(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "What should I copy?"
    if clipboard.set_text(text):
        _audit("Copied to clipboard", text)
        return "Copied to the clipboard."
    return "I could not write to the clipboard."


# --------------------------------------------------------------------------- #
#  Windows
# --------------------------------------------------------------------------- #
class _WindowInfo:
    __slots__ = ("hwnd", "title")

    def __init__(self, hwnd: int, title: str) -> None:
        self.hwnd = hwnd
        self.title = title


def list_windows() -> list[_WindowInfo]:
    user32 = ctypes.windll.user32
    found: list[_WindowInfo] = []
    ignore = {"Program Manager", "Windows Input Experience", "Settings", "Hepsini Simge Durumuna Küçült"}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if title and title not in ignore:
            found.append(_WindowInfo(hwnd, title))
        return True

    try:
        user32.EnumWindows(_callback, 0)
    except Exception:
        pass
    return found


def window_titles() -> str:
    titles = [window.title for window in list_windows()]
    if not titles:
        return "I cannot see any open windows."
    unique = list(dict.fromkeys(titles))[:8]
    return "Open windows: " + " | ".join(unique) + "."


def switch_window(name: str) -> str:
    query = (name or "").lower().strip()
    if not query:
        return "Which window should I switch to?"
    windows = list_windows()
    match = next((w for w in windows if query in w.title.lower()), None)
    if match is None:
        aliases = {"chrome": "chrome", "spotify": "spotify", "notepad": "notepad",
                   "code": "visual studio code", "word": "word", "excel": "excel",
                   "explorer": "file explorer", "edge": "edge", "terminal": "terminal"}
        wanted = aliases.get(query, query)
        match = next((w for w in windows if wanted in w.title.lower()), None)
    if match is None:
        return f"I could not find a window called {name}."
    user32 = ctypes.windll.user32
    try:
        user32.ShowWindow(match.hwnd, 9)
        user32.SwitchToThisWindow(match.hwnd, True)
    except Exception:
        pass
    _audit("Switched window", match.title)
    return f"Switched to {match.title}."


def show_desktop() -> str:
    press_key("win+d")
    _audit("Showed the desktop")
    return "Showing the desktop."

