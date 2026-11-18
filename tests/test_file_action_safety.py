from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import actions
import brain


class FileActionSafetyTests(unittest.TestCase):
    def test_organize_preview_creates_no_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(actions, "_audit"):
            folder = Path(tmp)
            (folder / "example.txt").write_text("hello", encoding="utf-8")
            result = actions.organize_folder(folder, dry_run=True)
            self.assertEqual(result["moved"], 1)
            self.assertEqual([p.name for p in folder.iterdir()], ["example.txt"])

    def test_find_duplicates_previews_and_never_removes_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(actions, "_audit"):
            folder = Path(tmp)
            a, b = folder / "a.txt", folder / "b.txt"
            a.write_text("same", encoding="utf-8")
            b.write_text("same", encoding="utf-8")
            result = actions.remove_duplicates(folder, dry_run=True)
            self.assertEqual(result["removed"], 1)
            self.assertTrue(a.exists() and b.exists())
            text = brain.Brain._format_duplicate_result(None, result, True)
            self.assertIn("No files were deleted", text)
            self.assertIn("b.txt", text)
            self.assertIn("error", actions.remove_duplicates(folder))
            self.assertTrue(a.exists() and b.exists())

    def test_folder_deletion_is_disabled_until_review_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(actions, "_audit"):
            folder = Path(tmp)
            empty = folder / "empty"
            empty.mkdir()
            result = actions.clean_empty_folders(folder, dry_run=True)
            self.assertEqual(result["removed"], 1)
            self.assertIn("No folders were deleted", brain.Brain._format_empty_folder_result(None, result, True))
            self.assertIn("error", actions.clean_empty_folders(folder))
            self.assertTrue(empty.exists())


if __name__ == "__main__":
    unittest.main()
