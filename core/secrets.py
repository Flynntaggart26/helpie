"""Windows DPAPI ile API anahtarını şifreleme (düz metin kalmasın)."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _to_blob(data: bytes):
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def protect(text: str) -> str:
    if not text:
        return ""
    try:
        raw = text.encode("utf-8")
        blob_in, _keep = _to_blob(raw)
        blob_out = _BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            return ""
        try:
            encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return base64.b64encode(encrypted).decode("ascii")
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return ""


def unprotect(token: str) -> str:
    if not token:
        return ""
    try:
        blob_in, _keep = _to_blob(base64.b64decode(token))
        blob_out = _BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            return ""
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData).decode("utf-8")
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return ""
