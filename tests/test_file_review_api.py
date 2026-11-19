from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import server


class FileReviewApiTests(unittest.TestCase):
    def handler(self, body: dict) -> server.Handler:
        handler = server.Handler.__new__(server.Handler)
        handler.app = Mock()
        handler.path = "/api/file-review/recheck"
        handler._trusted_local_request = Mock(return_value=True)
        handler._authorized_api = Mock(return_value=True)
        handler._body = Mock(return_value=body)
        handler._json = Mock()
        return handler

    def test_recycle_history_requires_auth_and_only_returns_broker_receipts(self) -> None:
        handler = self.handler({})
        handler.path = "/api/recycle/history"
        handler.app.recycle_broker.available.return_value = True
        handler.app.recycle_broker.recent.return_value = ["example.txt"]
        with patch.object(server.audit, "log") as log:
            handler.do_GET()
        handler._json.assert_called_once_with({"available": True, "items": ["example.txt"]})
        log.assert_called_once_with("Viewed Recycle Bin activity", source="files")
        handler = self.handler({})
        handler.path = "/api/recycle/history"
        handler._authorized_api.return_value = False
        handler.do_GET()
        handler.app.recycle_broker.recent.assert_not_called()
        handler._json.assert_not_called()

    def test_recheck_uses_fixed_root_and_audits(self) -> None:
        selected = [{"path": "item.txt", "fingerprint": "a" * 64}]
        handler = self.handler({"folder": "downloads", "kind": "duplicates", "selected": selected})
        with patch.object(server.file_review, "recheck", return_value={"items": []}) as recheck, \
             patch.object(server.audit, "log") as log:
            handler.do_POST()
        recheck.assert_called_once_with(Path.home() / "Downloads", "duplicates", selected)
        log.assert_called_once_with("Rechecked files without deletion", source="files")
        handler._json.assert_called_once_with({"items": []})

    def test_invalid_folder_and_selection_do_not_succeed(self) -> None:
        handler = self.handler({"folder": "../../", "kind": "duplicates", "selected": []})
        with patch.object(server.file_review, "recheck") as recheck:
            handler.do_POST()
        recheck.assert_not_called()
        self.assertEqual(handler._json.call_args.args[1], 400)
        handler = self.handler({"folder": "downloads", "kind": "duplicates", "selected": []})
        with patch.object(server.file_review, "recheck", side_effect=ValueError):
            handler.do_POST()
        self.assertEqual(handler._json.call_args.args[1], 400)

    def test_confirm_review_is_read_only_and_rejects_invalid_token(self) -> None:
        handler = self.handler({"token": "review-token"})
        handler.path = "/api/file-review/confirm-review"
        with patch.object(server.audit, "log") as log:
            handler.do_POST()
        handler.app.file_review_drafts.confirm.assert_called_once_with("review-token")
        log.assert_called_once_with("Confirmed read-only file review", source="files")
        handler._json.assert_called_once_with({"ok": True, "deleted": False})
        handler = self.handler({"token": "wrong"})
        handler.path = "/api/file-review/confirm-review"
        handler.app.file_review_drafts.confirm.side_effect = ValueError
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[1], 409)

    def test_prepare_and_cancel_use_read_only_draft(self) -> None:
        selected = [{"path": "item", "fingerprint": "a" * 64}]
        handler = self.handler({"folder": "downloads", "kind": "duplicates", "selected": selected})
        handler.path = "/api/file-review/prepare-review"
        handler.app.file_review_drafts.prepare.return_value = "temporary-token"
        with patch.object(server.audit, "log") as log:
            handler.do_POST()
        handler.app.file_review_drafts.prepare.assert_called_once_with(Path.home() / "Downloads", "duplicates", selected)
        handler._json.assert_called_once_with({"token": "temporary-token", "expires_in_seconds": 60.0})
        log.assert_called_once_with("Prepared read-only file review", source="files")
        handler = self.handler({})
        handler.path = "/api/file-review/cancel-review"
        with patch.object(server.audit, "log") as log:
            handler.do_POST()
        log.assert_called_once_with("Cancelled read-only file review", source="files")
        handler.app.file_review_drafts.cancel.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
