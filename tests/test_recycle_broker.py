from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import recycle_broker


class RecycleBrokerTests(unittest.TestCase):
    def test_display_exposes_direction_controls_without_changing_other_characters(self) -> None:
        self.assertEqual(recycle_broker.safe_display_path("ödev\u202ecod.exe\n"),
                         "ödev\\u202ecod.exe\\u000a")

    def setUp(self) -> None:
        self.item = recycle_broker.RecycleCandidate("example.txt", b"immutable-id")
        self.verify = Mock(return_value=True)
        self.move = Mock(return_value=True)
        self.broker = recycle_broker.RecycleBroker(self.verify, self.move)

    def test_no_adapter_fails_closed(self) -> None:
        broker = recycle_broker.RecycleBroker(self.verify)
        with self.assertRaises(ValueError):
            broker.prepare(self.item)
        self.verify.assert_not_called()
        self.assertEqual(broker.recent(), [])
        self.assertFalse(broker.available())

    def test_explicit_approval_is_one_shot_and_records_only_success(self) -> None:
        token = self.broker.prepare(self.item)
        self.move.assert_not_called()
        result = self.broker.confirm(token, approved=True)
        self.assertEqual(result, {"recycled": True, "items": ["example.txt"]})
        self.assertEqual(self.broker.recent(), ["example.txt"])
        with self.assertRaises(ValueError):
            self.broker.confirm(token, approved=True)
        self.move.assert_called_once()

    def test_no_approval_changed_item_or_expiration_does_not_move(self) -> None:
        token = self.broker.prepare(self.item)
        with self.assertRaises(ValueError):
            self.broker.confirm(token, approved=False)
        token = self.broker.prepare(self.item)
        self.verify.return_value = False
        with self.assertRaises(ValueError):
            self.broker.confirm(token, approved=True)
        self.verify.return_value = True
        with patch.object(recycle_broker.time, "monotonic", side_effect=[10.0, 71.0]):
            token = self.broker.prepare(self.item)
            with self.assertRaises(ValueError):
                self.broker.confirm(token, approved=True)
        self.move.assert_not_called()
        self.assertEqual(self.broker.recent(), [])

    def test_failed_or_unverified_move_is_not_listed(self) -> None:
        for result in (False, None, 1):
            with self.subTest(result=result):
                self.move.return_value = result
                token = self.broker.prepare(self.item)
                self.assertEqual(self.broker.confirm(token, approved=True), {"recycled": False, "items": []})
                self.assertEqual(self.broker.recent(), [])
        self.move.side_effect = OSError("simulated failure")
        token = self.broker.prepare(self.item)
        with self.assertRaises(OSError):
            self.broker.confirm(token, approved=True)
        self.assertEqual(self.broker.recent(), [])

    def test_cancel_before_and_during_operation(self) -> None:
        token = self.broker.prepare(self.item)
        self.broker.cancel()
        with self.assertRaises(ValueError):
            self.broker.confirm(token, approved=True)
        entered, finish = threading.Event(), threading.Event()
        def fake_move(_item, cancel):
            entered.set()
            finish.wait(3)
            return not cancel.is_set()
        self.move.side_effect = fake_move
        token = self.broker.prepare(self.item)
        result = []
        worker = threading.Thread(target=lambda: result.append(self.broker.confirm(token, approved=True)))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(ValueError):
                self.broker.prepare(self.item)
            self.broker.cancel()
        finally:
            finish.set()
            worker.join(3)
        self.assertEqual(result, [{"recycled": False, "items": []}])
        self.assertEqual(self.broker.recent(), [])

    def test_success_after_late_cancel_is_reported_honestly(self) -> None:
        entered, finish = threading.Event(), threading.Event()
        def fake_move(_item, _cancel):
            entered.set()
            finish.wait(3)
            return True
        self.move.side_effect = fake_move
        token = self.broker.prepare(self.item)
        result = []
        worker = threading.Thread(target=lambda: result.append(self.broker.confirm(token, approved=True)))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.broker.cancel()
        finally:
            finish.set()
            worker.join(3)
        self.assertEqual(result, [{"recycled": True, "items": ["example.txt"]}])
        self.assertEqual(self.broker.recent(), ["example.txt"])

    def test_cancel_during_preflight_invalidates_proposal(self) -> None:
        entered, finish = threading.Event(), threading.Event()
        def fake_verify(_item):
            entered.set()
            finish.wait(3)
            return True
        self.verify.side_effect = fake_verify
        result = []
        def prepare():
            try:
                self.broker.prepare(self.item)
                result.append("prepared")
            except ValueError:
                result.append("cancelled")
        worker = threading.Thread(target=prepare)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.broker.cancel()
        finally:
            finish.set()
            worker.join(3)
        self.assertEqual(result, ["cancelled"])
        self.move.assert_not_called()

    def test_explicit_bool_and_immutable_identity_are_required(self) -> None:
        invalid = recycle_broker.RecycleCandidate("example.txt", bytearray(b"id"))
        with self.assertRaises(ValueError):
            self.broker.prepare(invalid)
        token = self.broker.prepare(self.item)
        with self.assertRaises(ValueError):
            self.broker.confirm(token, approved=1)
        self.move.assert_not_called()


if __name__ == "__main__":
    unittest.main()
