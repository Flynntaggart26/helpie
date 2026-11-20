from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import approval_drafts
import config
import memory
import server


class DataActionApprovalTests(unittest.TestCase):
    def test_one_use_expiration_cancel_and_target_binding(self) -> None:
        drafts = approval_drafts.ApprovalDrafts()
        token, preview = drafts.prepare("forget_memory", {"text": "coffee"})
        self.assertIn("coffee", preview)
        proposal = drafts.consume(token)
        self.assertEqual(proposal.args, {"text": "coffee"})
        with self.assertRaises(ValueError):
            drafts.consume(token)
        token, _ = drafts.prepare("delete_routine", {"name": "morning"})
        drafts.cancel("different token")
        self.assertEqual(drafts.consume(token).args, {"name": "morning"})
        token, _ = drafts.prepare("clear_memory", {})
        drafts.cancel(token)
        with self.assertRaises(ValueError):
            drafts.consume(token)
        with patch.object(approval_drafts.time, "monotonic", side_effect=[10, 70]):
            token, _ = drafts.prepare("clear_memory", {})
            with self.assertRaises(ValueError):
                drafts.consume(token)
        with self.assertRaises(ValueError):
            drafts.prepare("power", {"mode": "shutdown"})

    def test_memory_removal_requires_exact_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "DATA_DIR", Path(directory)):
            memory.add("I like coffee")
            memory.add("I like coffee and tea")
            self.assertFalse(memory.remove("coffee"))
            self.assertEqual(len(memory.list_items()), 2)
            self.assertTrue(memory.remove("I like coffee"))
            self.assertEqual([item["text"] for item in memory.list_items()], ["I like coffee and tea"])

    def test_old_destructive_endpoints_are_blocked(self) -> None:
        for path in ("/api/memory/clear", "/api/memory/delete", "/api/routines/delete"):
            with self.subTest(path=path):
                handler = server.Handler.__new__(server.Handler)
                handler.app = Mock()
                handler.path = path
                handler._trusted_local_request = Mock(return_value=True)
                handler._authorized_api = Mock(return_value=True)
                handler._body = Mock(return_value={})
                handler._json = Mock()
                with patch.object(memory, "clear") as clear, patch.object(memory, "remove") as remove:
                    handler.do_POST()
                clear.assert_not_called()
                remove.assert_not_called()
                self.assertEqual(handler._json.call_args.args[1], 403)

    def test_ui_prepare_confirm_and_replay(self) -> None:
        handler = server.Handler.__new__(server.Handler)
        handler.app = Mock()
        handler.app.ui_action_drafts = approval_drafts.ApprovalDrafts()
        handler.app.brain._dispatch.return_value = "Forgotten."
        handler._trusted_local_request = Mock(return_value=True)
        handler._authorized_api = Mock(return_value=True)
        handler._json = Mock()
        handler.path = "/api/action-approval/prepare"
        handler._body = Mock(return_value={"action": "forget_memory", "args": {"text": "coffee"}})
        with patch.object(server.audit, "log"):
            handler.do_POST()
        token = handler._json.call_args.args[0]["token"]
        handler.app.brain._dispatch.assert_not_called()
        handler.path = "/api/action-approval/confirm"
        handler._body.return_value = {"token": token}
        handler.do_POST()
        handler.app.brain._dispatch.assert_called_once_with("forget_memory", {"text": "coffee"}, confirmed=True)
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[1], 400)
        handler.app.brain._dispatch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
