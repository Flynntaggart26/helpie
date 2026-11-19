"""Read Windows file identity from a handle; this module never deletes files.

The final path component is opened without following a reparse point. This is
not by itself a containment check or permission to delete: parent-directory
redirection and changes after the handle is closed must be handled separately.
"""
from __future__ import annotations

import ctypes
import os
from contextlib import ExitStack, contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator

FILE_READ_ATTRIBUTES = 0x80
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
FILE_SHARE_DELETE = 0x4
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ID_INFO_CLASS = 18
FILE_BASIC_INFO_CLASS = 0
FILE_STANDARD_INFO_CLASS = 1


class _FileIdInfo(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_uint64), ("file_id", ctypes.c_ubyte * 16)]


class _FileBasicInfo(ctypes.Structure):
    _fields_ = [("creation", ctypes.c_int64), ("access", ctypes.c_int64),
                ("write", ctypes.c_int64), ("change", ctypes.c_int64),
                ("attributes", ctypes.c_uint32)]


class _FileStandardInfo(ctypes.Structure):
    _fields_ = [("allocation_size", ctypes.c_int64), ("size", ctypes.c_int64),
                ("links", ctypes.c_uint32), ("delete_pending", ctypes.c_ubyte),
                ("directory", ctypes.c_ubyte)]


@dataclass(frozen=True)
class FileIdentity:
    volume: int
    file_id: bytes
    creation_time: int
    write_time: int
    change_time: int
    size: int
    links: int
    directory: bool


def _kernel32():
    if os.name != "nt":
        raise OSError("Windows file identity is not available on this platform.")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  wintypes.LPVOID, wintypes.DWORD]
    api.GetFileInformationByHandleEx.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    api.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    api.GetDriveTypeW.restype = wintypes.UINT
    return api


@contextmanager
def open_identity(path: Path, *, share_mode: int = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                  desired_access: int = FILE_READ_ATTRIBUTES) -> Iterator[tuple[int, FileIdentity]]:
    """Open one final component and return its 128-bit file ID and metadata.

    The caller may inspect the still-open handle inside the context. Callers
    in this module request read-only access and cannot remove the object.
    """
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("An absolute path is required.")
    if desired_access not in (FILE_READ_ATTRIBUTES, GENERIC_READ):
        raise ValueError("Only read-only file handles are supported.")
    api = _kernel32()
    handle = api.CreateFileW(str(path), desired_access, share_mode,
                             None, OPEN_EXISTING,
                             FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        identity = _FileIdInfo()
        basic = _FileBasicInfo()
        standard = _FileStandardInfo()
        for info_class, info in ((FILE_ID_INFO_CLASS, identity), (FILE_BASIC_INFO_CLASS, basic),
                                 (FILE_STANDARD_INFO_CLASS, standard)):
            if not api.GetFileInformationByHandleEx(handle, info_class, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
        if basic.attributes & FILE_ATTRIBUTE_REPARSE_POINT or standard.delete_pending:
            raise ValueError("Reparse points and deletion-pending objects are not supported.")
        yield handle, FileIdentity(identity.volume, bytes(identity.file_id), basic.creation,
                                   basic.write, basic.change, standard.size,
                                   standard.links, bool(standard.directory))
    finally:
        api.CloseHandle(handle)


def read_identity(path: Path) -> FileIdentity:
    with open_identity(path) as (_, identity):
        return identity


@contextmanager
def open_guarded(root: Path, relative_name: str) -> Iterator[tuple[int, FileIdentity]]:
    """Hold each parent against renames and the final target against writes.

    This read-only guard does not delete or authorize deletion. The opened
    handles must remain open throughout any later action-bound verification.
    """
    root = Path(root)
    if (not root.is_absolute() or not root.drive or root.drive.startswith("\\\\") or ".." in root.parts
            or not isinstance(relative_name, str) or not relative_name
            or "\\" in relative_name or ":" in relative_name):
        raise ValueError("Expected an absolute local root and relative item name.")
    relative = PurePosixPath(relative_name)
    if (relative.is_absolute() or not relative.parts or len(root.parts) + len(relative.parts) > 64
            or any(part in (".", "..") for part in relative.parts)):
        raise ValueError("Invalid relative item name.")
    if _kernel32().GetDriveTypeW(root.anchor) not in (2, 3):  # removable or fixed local drive
        raise ValueError("Only local drives are supported.")
    # Lock all directories from the volume root, including ancestors outside
    # the chosen folder. This refuses junctions rather than following them.
    with ExitStack() as stack:
        current = Path(root.anchor)
        _, parent_identity = stack.enter_context(open_identity(current, share_mode=FILE_SHARE_READ | FILE_SHARE_WRITE,
                                                               desired_access=GENERIC_READ))
        if not parent_identity.directory:
            raise ValueError("Expected a directory in the parent chain.")
        for component in (*root.parts[1:], *relative.parts[:-1]):
            current /= component
            _, parent_identity = stack.enter_context(open_identity(current, share_mode=FILE_SHARE_READ | FILE_SHARE_WRITE,
                                                                   desired_access=GENERIC_READ))
            if not parent_identity.directory:
                raise ValueError("Expected a directory in the parent chain.")
        yield stack.enter_context(open_identity(current / relative.parts[-1], share_mode=FILE_SHARE_READ,
                                                desired_access=GENERIC_READ))


def read_guarded_identity(root: Path, relative_name: str) -> FileIdentity:
    with open_guarded(root, relative_name) as (_, identity):
        return identity
