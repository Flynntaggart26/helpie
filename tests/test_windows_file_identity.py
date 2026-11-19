from __future__ import annotations

import os
import ctypes
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import windows_file_identity
import file_review


@unittest.skipUnless(os.name == "nt", "Windows handle API required")
class WindowsFileIdentityTests(unittest.TestCase):
    def test_real_file_and_directory_handles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / "first.txt", root / "second.txt"
            first.write_bytes(b"same")
            second.write_bytes(b"same")
            original = windows_file_identity.read_identity(first)
            self.assertEqual(len(original.file_id), 16)
            self.assertEqual(original.size, 4)
            self.assertFalse(original.directory)
            self.assertNotEqual(original.file_id, windows_file_identity.read_identity(second).file_id)
            self.assertTrue(windows_file_identity.read_identity(root).directory)
            self.assertEqual(original, windows_file_identity.read_identity(first))

    def test_modified_file_and_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            item = Path(tmp) / "item"
            item.write_bytes(b"one")
            original = windows_file_identity.read_identity(item)
            item.write_bytes(b"longer content")
            self.assertNotEqual(original, windows_file_identity.read_identity(item))
            with self.assertRaises(OSError):
                windows_file_identity.read_identity(Path(tmp) / "missing")

    def test_read_only_review_uses_real_handle_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty").mkdir()
            selected = file_review.preview(root, "empty_folders")["items"]
            drafts = file_review.ReviewDrafts(native_reader=windows_file_identity.read_guarded_identity)
            token = drafts.prepare(root, "empty_folders", selected)
            drafts.confirm(token)
            self.assertTrue((root / "empty").is_dir())

    def test_review_refuses_changed_file_after_native_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty").mkdir()
            selected = file_review.preview(root, "empty_folders")["items"]
            drafts = file_review.ReviewDrafts(native_reader=windows_file_identity.read_guarded_identity)
            token = drafts.prepare(root, "empty_folders", selected)
            (root / "empty" / "item.txt").write_bytes(b"new")
            with self.assertRaises(ValueError):
                drafts.confirm(token)
            self.assertTrue((root / "empty" / "item.txt").exists())

    def test_guard_blocks_new_writable_handle_for_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "item.txt"
            target.write_bytes(b"unchanged")
            with windows_file_identity.open_guarded(root, "item.txt") as (_, info):
                self.assertEqual(info.size, 9)
                with self.assertRaises(OSError):
                    with target.open("r+b"):
                        self.fail("A writable handle was opened while the guard was held")
                api = windows_file_identity._kernel32()
                handle = api.CreateFileW(str(target), 0x00010000, 7, None, 3, 0, None)
                if handle != ctypes.c_void_p(-1).value:
                    api.CloseHandle(handle)
                    self.fail("Target could be opened for deletion while guarded")
            self.assertEqual(target.read_bytes(), b"unchanged")

    def test_guard_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("..", "../outside", "/outside", "C:/outside", "folder\\item", ".", "/".join(["x"] * 65)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    with windows_file_identity.open_guarded(root, name):
                        self.fail("Unsafe path was accepted")

    def test_guard_blocks_delete_access_to_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "parent"
            parent.mkdir()
            (parent / "item").write_bytes(b"x")
            with windows_file_identity.open_guarded(root, "parent/item"):
                api = windows_file_identity._kernel32()
                handle = api.CreateFileW(str(parent), 0x00010000, 7, None, 3,
                                         windows_file_identity.FILE_FLAG_BACKUP_SEMANTICS, None)
                if handle != ctypes.c_void_p(-1).value:
                    api.CloseHandle(handle)
                    self.fail("A parent directory could be opened for deletion while guarded")

    def test_reparse_point_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, link = root / "source", root / "link"
            source.write_bytes(b"x")
            try:
                os.symlink(source, link)
            except OSError:
                self.skipTest("Creating symbolic links requires a Windows privilege")
            with self.assertRaises(ValueError):
                windows_file_identity.read_identity(link)

    def test_reparse_attribute_fails_closed_without_link_privilege(self) -> None:
        api = Mock()
        api.CreateFileW.return_value = 1
        def information(_handle, kind, pointer, _size):
            if kind == windows_file_identity.FILE_BASIC_INFO_CLASS:
                basic = ctypes.cast(pointer, ctypes.POINTER(windows_file_identity._FileBasicInfo))
                basic.contents.attributes = windows_file_identity.FILE_ATTRIBUTE_REPARSE_POINT
            return 1
        api.GetFileInformationByHandleEx.side_effect = information
        with patch.object(windows_file_identity, "_kernel32", return_value=api):
            with self.assertRaises(ValueError):
                windows_file_identity.read_identity(Path("C:/fake-link"))
        api.CloseHandle.assert_called_once_with(1)

    def test_identity_handle_rejects_delete_access(self) -> None:
        with self.assertRaises(ValueError):
            with windows_file_identity.open_identity(Path("C:/test"), desired_access=0x10000):
                self.fail("Delete access must not be allowed by the read-only guard")


if __name__ == "__main__":
    unittest.main()
