from __future__ import annotations

import sys
import os
import tempfile
import threading
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
            self.assertEqual([{k: v for k, v in row.items() if k != "fingerprint"} for row in result["items"]],
                             [{"path": "b.txt", "matches": "a.txt", "size": 4}])
            self.assertEqual(len(result["items"][0]["fingerprint"]), 64)
            self.assertFalse(result["limited"])
            self.assertEqual((root / "b.txt").read_text(encoding="utf-8"), "same")

    def test_empty_folders_and_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty").mkdir()
            (root / "nonempty").mkdir()
            (root / "nonempty" / "x").write_text("x", encoding="utf-8")
            result = file_review.preview(root, "empty_folders")
            self.assertEqual([row["path"] for row in result["items"]], ["empty"])
            self.assertTrue((root / "empty").exists())
            with patch.object(file_review, "MAX_ENTRIES", 1):
                self.assertTrue(file_review.preview(root, "empty_folders")["limited"])

    def test_invalid_kind_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                file_review.preview(Path(tmp), "delete")

    def test_recheck_detects_changes_to_duplicate_or_keeper(self) -> None:
        for changed in ("a.txt", "b.txt"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "a.txt").write_text("same", encoding="utf-8")
                (root / "b.txt").write_text("same", encoding="utf-8")
                selected = file_review.preview(root, "duplicates")["items"]
                self.assertTrue(file_review.recheck(root, "duplicates", selected)["items"][0]["unchanged"])
                (root / changed).write_text("else", encoding="utf-8")
                self.assertFalse(file_review.recheck(root, "duplicates", selected)["items"][0]["unchanged"])
                self.assertTrue((root / "a.txt").exists())
                self.assertTrue((root / "b.txt").exists())

    def test_recheck_detects_folder_no_longer_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty").mkdir()
            selected = file_review.preview(root, "empty_folders")["items"]
            self.assertTrue(file_review.recheck(root, "empty_folders", selected)["items"][0]["unchanged"])
            (root / "empty" / "new.txt").write_text("x", encoding="utf-8")
            self.assertFalse(file_review.recheck(root, "empty_folders", selected)["items"][0]["unchanged"])

    def test_recheck_detects_both_duplicates_changing_to_same_new_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").write_bytes(b"same")
            (root / "b").write_bytes(b"same")
            selected = file_review.preview(root, "duplicates")["items"]
            (root / "a").write_bytes(b"else")
            (root / "b").write_bytes(b"else")
            self.assertFalse(file_review.recheck(root, "duplicates", selected)["items"][0]["unchanged"])

    def test_recheck_rejects_invalid_or_duplicate_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for selected in ([], [{"path": "x", "fingerprint": "x"}],
                             [{"path": "x", "fingerprint": "a" * 64}] * 2,
                             [{"path": "x", "fingerprint": "a" * 64}] * 101):
                with self.subTest(selected=selected), self.assertRaises(ValueError):
                    file_review.recheck(root, "empty_folders", selected)

    def test_read_only_review_confirmation_is_single_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty").mkdir()
            selected = file_review.preview(root, "empty_folders")["items"]
            drafts = file_review.ReviewDrafts()
            token = drafts.prepare(root, "empty_folders", selected)
            drafts.confirm(token)
            self.assertTrue((root / "empty").is_dir())
            with self.assertRaises(ValueError):
                drafts.confirm(token)

    def test_confirmation_fails_when_folder_changes_or_is_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty").mkdir()
            selected = file_review.preview(root, "empty_folders")["items"]
            drafts = file_review.ReviewDrafts()
            token = drafts.prepare(root, "empty_folders", selected)
            (root / "empty" / "new.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                drafts.confirm(token)
            self.assertTrue((root / "empty" / "new.txt").exists())
            with self.assertRaises(ValueError):
                drafts.prepare(root, "empty_folders", selected)

    def test_confirmation_expiry_and_limited_scan_fail_closed(self) -> None:
        drafts = file_review.ReviewDrafts()
        selected = [{"path": "x", "fingerprint": "a" * 64}]
        with patch.object(file_review, "recheck", return_value={"limited": False, "items": [{"unchanged": True}]}), \
             patch.object(file_review.time, "monotonic", side_effect=[10.0, 71.0]):
            token = drafts.prepare(Path("."), "empty_folders", selected)
            with self.assertRaises(ValueError):
                drafts.confirm(token)
        with patch.object(file_review, "recheck", return_value={"limited": True, "items": [{"unchanged": True}]}):
            with self.assertRaises(ValueError):
                drafts.prepare(Path("."), "empty_folders", selected)

    def test_native_identity_change_cannot_confirm_review(self) -> None:
        selected = [{"path": "folder/item", "fingerprint": "a" * 64}]
        valid = {"limited": False, "items": [{"unchanged": True}]}
        identities = iter(["old-identity", "new-identity"])
        drafts = file_review.ReviewDrafts(native_reader=lambda root, name: next(identities))
        with patch.object(file_review, "recheck", return_value=valid):
            token = drafts.prepare(Path("C:/test"), "empty_folders", selected)
            with self.assertRaises(ValueError):
                drafts.confirm(token)

    def test_native_snapshot_rejects_parent_and_absolute_paths(self) -> None:
        valid = {"limited": False, "items": [{"unchanged": True}]}
        drafts = file_review.ReviewDrafts(native_reader=lambda root, name: "identity")
        for name in ("../outside", "/outside", "C:/outside", "dir\\outside"):
            with self.subTest(path=name), patch.object(file_review, "recheck", return_value=valid), self.assertRaises(ValueError):
                drafts.prepare(Path("C:/test"), "empty_folders", [{"path": name, "fingerprint": "a" * 64}])

    def test_cancel_while_preparing_does_not_create_draft(self) -> None:
        entered, resume = threading.Event(), threading.Event()
        drafts = file_review.ReviewDrafts()
        outcomes = []
        def blocked(*_args):
            entered.set()
            resume.wait(3)
            return {"limited": False, "items": [{"unchanged": True}]}
        def prepare():
            try:
                drafts.prepare(Path("."), "empty_folders", [{"path": "x", "fingerprint": "a" * 64}])
                outcomes.append("created")
            except ValueError:
                outcomes.append("cancelled")
        with patch.object(file_review, "recheck", side_effect=blocked):
            worker = threading.Thread(target=prepare)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                drafts.cancel()
            finally:
                resume.set()
                worker.join(3)
        self.assertEqual(outcomes, ["cancelled"])

    def test_cancel_while_confirming_invalidates_review(self) -> None:
        entered, resume = threading.Event(), threading.Event()
        drafts = file_review.ReviewDrafts()
        selected = [{"path": "x", "fingerprint": "a" * 64}]
        valid = {"limited": False, "items": [{"unchanged": True}]}
        with patch.object(file_review, "recheck", return_value=valid):
            token = drafts.prepare(Path("."), "empty_folders", selected)
        outcomes = []
        def blocked(*_args):
            entered.set()
            resume.wait(3)
            return valid
        def confirm():
            try:
                drafts.confirm(token)
                outcomes.append("confirmed")
            except ValueError:
                outcomes.append("cancelled")
        with patch.object(file_review, "recheck", side_effect=blocked):
            worker = threading.Thread(target=confirm)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                drafts.cancel()
            finally:
                resume.set()
                worker.join(3)
        self.assertEqual(outcomes, ["cancelled"])

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
