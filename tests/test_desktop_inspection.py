from __future__ import annotations

import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import desktop_inspection as desktop


class DesktopInspectionTests(unittest.TestCase):
    def test_window_tokens_expire_and_reject_changed_window(self) -> None:
        current = [types.SimpleNamespace(hwnd=12, title="Editor")]
        selections = desktop.WindowSelections(lambda: current, lambda _hwnd: 42)
        with patch.object(desktop.time, "monotonic", return_value=100):
            windows, limited = selections.refresh()
            token = windows[0]["token"]
            self.assertFalse(limited)
            self.assertEqual(selections.resolve(token), 12)
        current[0].title = "Different document"
        with patch.object(desktop.time, "monotonic", return_value=101):
            with self.assertRaises(ValueError):
                selections.resolve(token)
        current[0].title = "Editor"
        with patch.object(desktop.time, "monotonic", return_value=160):
            with self.assertRaises(ValueError):
                selections.resolve(token)

    def test_refresh_invalidates_old_tokens_and_clear_discards_them(self) -> None:
        windows = [types.SimpleNamespace(hwnd=7, title="Window")]
        selections = desktop.WindowSelections(lambda: windows, lambda _hwnd: 1)
        old = selections.refresh()[0][0]["token"]
        new = selections.refresh()[0][0]["token"]
        with self.assertRaises(ValueError):
            selections.resolve(old)
        selections.clear()
        with self.assertRaises(ValueError):
            selections.resolve(new)

    def test_inspection_timeout_blocks_parallel_requests_until_worker_exits(self) -> None:
        entered, release = threading.Event(), threading.Event()
        def slow(_hwnd):
            entered.set()
            release.wait(2)
            return []
        fake = types.ModuleType("comtypes")
        fake.__path__ = []
        fake.client = types.ModuleType("comtypes.client")
        with patch.dict(sys.modules, {"comtypes": fake, "comtypes.client": fake.client}), \
             patch.object(desktop, "_inspect", side_effect=slow), \
             patch.object(desktop, "INSPECT_TIMEOUT", 0.02):
            try:
                with self.assertRaises(TimeoutError):
                    desktop.inspect_window(7)
                self.assertTrue(entered.is_set())
                with self.assertRaises(RuntimeError):
                    desktop.inspect_window(7)
            finally:
                release.set()
                deadline = time.monotonic() + 2
                while desktop._inspection_gate.locked() and time.monotonic() < deadline:
                    time.sleep(0.005)
            self.assertFalse(desktop._inspection_gate.locked())


if __name__ == "__main__":
    unittest.main()
