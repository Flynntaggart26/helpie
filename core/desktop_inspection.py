"""Opt-in, read-only Windows control inspection; never clicks or types."""
from __future__ import annotations

import os
import secrets
import threading
import time
from collections import deque

MAX_WINDOWS = 50
MAX_CONTROLS = 40
MAX_VISITED = 160
WINDOW_TTL = 60.0
INSPECT_TIMEOUT = 3.0
_inspection_gate = threading.Lock()


class WindowSelections:
    def __init__(self, window_source, pid_source) -> None:
        self._windows = window_source
        self._pid = pid_source
        self._lock = threading.Lock()
        self._snapshot = {}

    def refresh(self) -> tuple[list[dict], bool]:
        windows = self._windows()
        expiry = time.monotonic() + WINDOW_TTL
        snapshot, result = {}, []
        for window in windows[:MAX_WINDOWS]:
            title = window.title[:200] if isinstance(window.title, str) else ""
            pid = self._pid(window.hwnd)
            if not title or not pid:
                continue
            token = secrets.token_hex(24)
            snapshot[token] = (window.hwnd, pid, window.title, expiry)
            result.append({"token": token, "title": title})
        with self._lock:
            self._snapshot = snapshot
        return result, len(windows) > MAX_WINDOWS

    def resolve(self, token: object) -> int:
        if not isinstance(token, str) or len(token) != 48 or not token.isascii():
            raise ValueError("Invalid window selection.")
        with self._lock:
            item = self._snapshot.get(token)
        if not item or time.monotonic() >= item[3]:
            raise ValueError("Window selection expired. List windows again.")
        hwnd, pid, title, _ = item
        if self._pid(hwnd) != pid or not any(w.hwnd == hwnd and w.title == title for w in self._windows()):
            raise ValueError("The selected window changed. List windows again.")
        return hwnd

    def clear(self) -> None:
        with self._lock:
            self._snapshot = {}


def _inspect(hwnd: int) -> list[dict]:
    if os.name != "nt":
        raise OSError("Windows UI Automation is unavailable.")
    import comtypes
    import comtypes.client
    comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    automation = root = walker = parent = child = None
    queue = deque()
    try:
        uia = comtypes.client.GetModule("UIAutomationCore.dll")
        automation = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)
        root = automation.ElementFromHandle(hwnd)
        walker = automation.ControlViewWalker
        queue = deque([(root, 0)])
        controls, visited = [], 0
        if root.CurrentControlType == uia.UIA_ButtonControlTypeId and not root.CurrentIsPassword and root.CurrentName:
            controls.append({"name": str(root.CurrentName)[:120], "type": "button"})
        while queue and visited < MAX_VISITED and len(controls) < MAX_CONTROLS:
            parent, depth = queue.popleft()
            if depth >= 6:
                continue
            child = walker.GetFirstChildElement(parent)
            while child and visited < MAX_VISITED and len(controls) < MAX_CONTROLS:
                visited += 1
                try:
                    if (child.CurrentControlType == uia.UIA_ButtonControlTypeId
                            and not child.CurrentIsPassword and child.CurrentName):
                        controls.append({"name": str(child.CurrentName)[:120], "type": "button"})
                    queue.append((child, depth + 1))
                    child = walker.GetNextSiblingElement(child)
                except Exception:
                    break
        return controls
    finally:
        # Release apartment-bound interfaces before uninitializing COM.
        queue.clear()
        automation = root = walker = parent = child = None
        comtypes.CoUninitialize()


def inspect_window(hwnd: int) -> list[dict]:
    """Run one read-only inspection at a time; fail closed on timeout."""
    if os.name == "nt":
        # Importing comtypes initializes COM on the importing thread. Do it
        # here so the worker can explicitly initialize its own MTA apartment.
        try:
            import comtypes.client  # noqa: F401
        except Exception as exc:
            raise RuntimeError("Windows UI Automation is unavailable.") from exc
    if not _inspection_gate.acquire(blocking=False):
        raise RuntimeError("A window inspection is already running.")
    result, errors = [], []
    def worker() -> None:
        try:
            result.extend(_inspect(hwnd))
        except Exception as exc:
            errors.append(exc)
        finally:
            _inspection_gate.release()
    thread = threading.Thread(target=worker, daemon=True, name="helpie-window-inspection")
    try:
        thread.start()
    except Exception:
        _inspection_gate.release()
        raise
    thread.join(INSPECT_TIMEOUT)
    if thread.is_alive():
        raise TimeoutError("Window inspection timed out.")
    if errors:
        raise RuntimeError("Window inspection failed.") from errors[0]
    return result
