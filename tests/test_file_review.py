from __future__ import annotations

import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import file_review


class FileReviewTests(unittest.TestCase):
    def test_duplicates_are_individual_read_only_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("same", encoding="utf-8")
            (root / "b.txt").write_text("same", encoding="utf-8")
            (root / "c.txt").write_text("else", encoding="utf-8")
            result = file_review.preview(root, "duplicates")
            self.assertEqual(result["items"], [{"path": "b.txt", "matches": "a.txt", "size": 4}])
            self.assertFalse(result["limited"])
            self.assertEqual((root / "b.txt").read_text(encoding="utf-8"), "same")

    def test_empty_folders_and_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty").mkdir()
            (root / "nonempty").mkdir()
            (root / "nonempty" / "x").write_text("x", encoding="utf-8")
            result = file_review.preview(root, "empty_folders")
            self.assertEqual(result["items"], [{"path": "empty"}])
            self.assertTrue((root / "empty").exists())
            with patch.object(file_review, "MAX_ENTRIES", 1):
                self.assertTrue(file_review.preview(root, "empty_folders")["limited"])

    def test_invalid_kind_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                file_review.preview(Path(tmp), "delete")

    def test_hash_budget_marks_incomplete_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").write_bytes(b"same")
            (root / "b").write_bytes(b"same")
            with patch.object(file_review, "MAX_HASH_BYTES", 4):
                result = file_review.preview(root, "duplicates")
            self.assertTrue(result["limited"])
            self.assertEqual(result["items"], [])

    def test_hard_links_are_not_duplicate_copies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").write_bytes(b"same")
            try:
                os.link(root / "a", root / "b")
            except OSError:
                self.skipTest("Hard links unavailable")
            self.assertEqual(file_review.preview(root, "duplicates")["items"], [])


if __name__ == "__main__":
    unittest.main()
