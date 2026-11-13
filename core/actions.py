"""Things Helpie can do on your Windows machine."""
from __future__ import annotations

import ctypes
import datetime as dt
import os
import re
import subprocess
import threading
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Optional

import config

CREATE_NO_WINDOW = 0x08000000

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
        try:
            if target.endswith(":"):
                os.startfile(target)
            else:
                subprocess.Popen(["cmd", "/c", "start", "", target], creationflags=CREATE_NO_WINDOW)
            return f"Opening {key}."
        except Exception:
            return f"Could not open {key}."
    cleaned = re.sub(r"(app|application|program|uygulamasını|programını)\s*$", "", name.strip()).strip()
    cleaned = re.sub(r"['’]s?$", "", cleaned).strip()
    if not cleaned:
        return "Which app should I open?"
    try:
        subprocess.Popen(["cmd", "/c", "start", "", cleaned], creationflags=CREATE_NO_WINDOW)
        return f"Opening {cleaned}."
    except Exception:
        return f"I could not find an app called {cleaned}."


def close_app(name: str) -> str:
    key = resolve_app(name)
    if not key or not APPS[key]["proc"]:
        return f"I could not find {name} running."
    subprocess.Popen(["taskkill", "/IM", APPS[key]["proc"], "/F"],
                     creationflags=CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        return f"Volume set to {round(percent)} percent."
    except Exception:
        current = get_volume()
        if current is None:
            steps = max(1, int(percent / 2))
            _key(VK_VOLUME_UP, min(steps, 50))
            return f"Volume turned up towards {round(percent)} percent."
        diff = int(round((percent - current) / 2))
        _key(VK_VOLUME_UP if diff > 0 else VK_VOLUME_DOWN, min(abs(diff), 25))
        return f"Volume set to about {round(percent)} percent."


def volume(direction: str = "up", step: int = 4) -> str:
    if direction == "mute":
        _key(VK_VOLUME_MUTE)
        return "Muted."
    _key(VK_VOLUME_UP if direction == "up" else VK_VOLUME_DOWN, step)
    current = get_volume()
    word = "up" if direction == "up" else "down"
    if current is None:
        return f"Volume turned {word}."
    return f"Volume turned {word}. It is now {round(current)} percent."


def media(action: str) -> str:
    if action == "play":
        _key(VK_MEDIA_PLAY)
        return "Playing."
    if action == "next":
        _key(VK_MEDIA_NEXT)
        return "Next track."
    if action == "prev":
        _key(VK_MEDIA_PREV)
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
    webbrowser.open(url)
    return "Opened it."


def web_search(query: str, engine: str = "google") -> str:
    from urllib.parse import quote_plus

    if engine == "youtube":
        webbrowser.open(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
        return f"Searching YouTube for {query}."
    webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
    return f"Searching the web for {query}."


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
    webbrowser.open(url)
    return f"Opening {key}."


def weather(city: str = "") -> str:
    import requests

    try:
        place = city.strip()
        r = requests.get(f"https://wttr.in/{place}?format=%l:+%C,+%t&m",
                         timeout=10, headers={"User-Agent": "curl/8"})
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
    return f"Screenshot saved as {path.name}."


def lock_screen() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "Locking the screen."


def sleep_pc() -> str:
    _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return "Putting the computer to sleep."


def shutdown_pc(restart: bool = False) -> str:
    _run(["shutdown", "/r" if restart else "/s", "/t", "5"])
    return "Restarting in 5 seconds." if restart else "Shutting down in 5 seconds."


def cancel_shutdown() -> str:
    _run(["shutdown", "/a"])
    return "Shutdown cancelled."


def empty_recycle_bin() -> str:
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
def find_file(query: str) -> Optional[Path]:
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
                name = filename.lower()
                if query in name:
                    score = len(query) * 2
                else:
                    tokens = [t for t in re.split(r"\W+", query) if len(t) > 2]
                    score = sum(1 for t in tokens if t in name) * max(1, len(tokens))
                if score and (best is None or score > best[0]):
                    best = (score, Path(walk_root) / filename)
    return best[1] if best else None


def open_file(query: str) -> str:
    path = find_file(query)
    if not path:
        return f"I could not find a file called {query}."
    os.startfile(str(path))
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
            return f"Opening {alias}."
    os.startfile(str(Path.home()))
    return "Opening your home folder."


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

    def _fire():
        on_fire(f"Reminder: {label.strip() or 'your timer is done'}")

    timer = threading.Timer(seconds, _fire)
    timer.daemon = True
    timer.start()
    span = f"{int(seconds)} seconds" if seconds < 60 else f"{seconds / 60:.0f} minutes"
    return f"Timer set for {span}."
