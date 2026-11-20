from __future__ import annotations

import ctypes
import importlib.util
import os
import sys
import threading
import time
import unittest
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import desktop_inspection


@unittest.skipUnless(os.name == "nt" and importlib.util.find_spec("comtypes"),
                     "Windows and comtypes are required")
class WindowsDesktopInspectionTests(unittest.TestCase):
    def test_reads_only_own_hidden_test_button(self) -> None:
        user32 = ctypes.windll.user32
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        window = user32.CreateWindowExW(0, "STATIC", "Helpie isolated test", 0,
                                        0, 0, 300, 200, None, None, None, None)
        if not window:
            self.skipTest("A hidden test window cannot be created in this session")
        try:
            button = user32.CreateWindowExW(0, "BUTTON", "Test button", 0x50000000,
                                            10, 10, 100, 30, window, None, None, None)
            self.assertTrue(button)
            results, errors = [], []
            def inspect() -> None:
                try:
                    results.extend(desktop_inspection.inspect_window(button))
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=inspect, daemon=True)
            worker.start()
            message = wintypes.MSG()
            deadline = time.monotonic() + 5
            while worker.is_alive() and time.monotonic() < deadline:
                while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(message))
                    user32.DispatchMessageW(ctypes.byref(message))
                time.sleep(.005)
            worker.join(.1)
            self.assertFalse(worker.is_alive(), "UI Automation inspection timed out")
            self.assertFalse(errors, str(errors))
            self.assertIn({"name": "Test button", "type": "button"}, results)
        finally:
            user32.DestroyWindow(window)


if __name__ == "__main__":
    unittest.main()
