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


if __name__ == "__main__":
    unittest.main()
