"""Bounded read-only inventory for duplicate files and empty folders."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import threading
import time
from pathlib import Path

MAX_ENTRIES = 2000
MAX_RESULTS = 100
MAX_HASH_BYTES = 128 * 1024 * 1024
MAX_SECONDS = 8.0
DRAFT_SECONDS = 60.0


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _fingerprint(*values: object) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def preview(root: Path, kind: str) -> dict:
    if kind not in {"duplicates", "empty_folders"}:
        raise ValueError("Unknown review type.")
    if _is_link(root.lstat()) or not root.is_dir():
        raise ValueError("The selected folder must be a normal directory.")
    root = root.resolve(strict=True)
    deadline = time.monotonic() + MAX_SECONDS
    pending, files, empty = [root], [], []
    entries_seen = 0
    limited = False
    while pending:
        if time.monotonic() >= deadline or entries_seen >= MAX_ENTRIES:
            limited = True
            break
        folder = pending.pop()
        try:
            with os.scandir(folder) as scan:
                entries = []
                for entry in scan:
                    entries_seen += 1
                    if entries_seen > MAX_ENTRIES or time.monotonic() >= deadline:
                        limited = True
                        break
                    entries.append(entry)
            if not entries and folder != root and not limited:
                info = folder.lstat()
                if not _is_link(info) and stat.S_ISDIR(info.st_mode):
                    name = folder.relative_to(root).as_posix()
                    empty.append({"path": name, "fingerprint": _fingerprint("empty", name, _identity(info))})
                else:
                    limited = True
            for entry in entries:
                try:
                    info = os.stat(entry.path, follow_symlinks=False)
                    if _is_link(info):
                        continue
                    path = Path(entry.path)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path)
                    elif stat.S_ISREG(info.st_mode):
                        files.append((path, info))
                except OSError:
                    limited = True
        except OSError:
            limited = True
    if kind == "empty_folders":
        rows = sorted(empty, key=lambda item: item["path"])[:MAX_RESULTS]
        return {"root": str(root), "kind": kind, "items": rows,
                "limited": limited or len(empty) > MAX_RESULTS}
    groups: dict[int, list[tuple[Path, os.stat_result]]] = {}
    for path, info in files:
        groups.setdefault(info.st_size, []).append((path, info))
    hashes: dict[tuple[int, str], list[tuple[str, tuple[int, int, int, int, int]]]] = {}
    hashed_bytes = 0
    for size, candidates in groups.items():
        if len(candidates) < 2:
            continue
        for path, before in candidates:
            if time.monotonic() >= deadline or hashed_bytes + size > MAX_HASH_BYTES:
                limited = True
                continue
            try:
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if _is_link(opened) or _identity(opened) != _identity(before):
                        limited = True
                        continue
                    while True:
                        block = stream.read(1024 * 1024)
                        if not block:
                            break
                        hashed_bytes += len(block)
                        if hashed_bytes > MAX_HASH_BYTES or time.monotonic() >= deadline:
                            limited = True
                            break
                        digest.update(block)
                    after = os.fstat(stream.fileno())
                    if limited and hashed_bytes > MAX_HASH_BYTES:
                        continue
                    if _identity(after) != _identity(before) or time.monotonic() >= deadline:
                        limited = True
                        continue
                hashes.setdefault((size, digest.hexdigest()), []).append(
                    (path.relative_to(root).as_posix(), _identity(before)))
            except OSError:
                limited = True
    rows = []
    for (size, digest), entries in hashes.items():
        entries.sort()
        unique = []
        identities = set()
        for path, identity in entries:
            if identity[:2] not in identities:
                identities.add(identity[:2])
                unique.append((path, identity))
        if len(unique) > 1:
            keeper, keeper_identity = unique[0]
            rows.extend({"path": path, "matches": keeper, "size": size,
                         "fingerprint": _fingerprint("duplicate", path, identity, keeper, keeper_identity, digest)}
                        for path, identity in unique[1:])
    rows.sort(key=lambda item: item["path"])
    return {"root": str(root), "kind": kind, "items": rows[:MAX_RESULTS],
            "limited": limited or len(rows) > MAX_RESULTS}


def recheck(root: Path, kind: str, selected: list[dict]) -> dict:
    """Compare a previous read-only preview with a new bounded preview.

    A match is informational and must never authorize deletion: files can change
    immediately afterwards and the fingerprints are supplied by the caller.
    """
    if not isinstance(selected, list) or not 1 <= len(selected) <= MAX_RESULTS:
        raise ValueError("Select between 1 and 100 items.")
    seen = set()
    for item in selected:
        if not isinstance(item, dict):
            raise ValueError("Invalid selection.")
        path, fingerprint = item.get("path"), item.get("fingerprint")
        if (not isinstance(path, str) or not 1 <= len(path) <= 4096 or path in seen
                or not isinstance(fingerprint, str) or len(fingerprint) != 64
                or any(char not in "0123456789abcdef" for char in fingerprint)):
            raise ValueError("Invalid selection.")
        seen.add(path)
    current = preview(root, kind)
    fingerprints = {item["path"]: item["fingerprint"] for item in current["items"]}
    return {"root": current["root"], "kind": kind, "limited": current["limited"],
            "items": [{"path": item["path"], "unchanged": fingerprints.get(item["path"]) == item["fingerprint"]}
                      for item in selected]}


class ReviewDrafts:
    """One short-lived confirmation for a read-only review, never for deletion."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._draft = None
        self._generation = 0

    @staticmethod
    def _verify(root: Path, kind: str, selected: list[dict]) -> None:
        result = recheck(root, kind, selected)
        if result["limited"] or not all(item["unchanged"] for item in result["items"]):
            raise ValueError("Review is incomplete or items have changed.")

    def prepare(self, root: Path, kind: str, selected: list[dict]) -> str:
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._draft = None
        self._verify(root, kind, selected)
        token = os.urandom(32).hex()
        snapshot = [{"path": item["path"], "fingerprint": item["fingerprint"]} for item in selected]
        with self._lock:
            if generation != self._generation:
                raise ValueError("Review was cancelled.")
            self._draft = (token, time.monotonic() + DRAFT_SECONDS, root, kind, snapshot)
        return token

    def cancel(self) -> None:
        with self._lock:
            self._generation += 1
            self._draft = None

    def confirm(self, token: str) -> None:
        with self._lock:
            self._generation += 1
            generation = self._generation
            draft = self._draft
            self._draft = None
        if (not isinstance(token, str) or not token.isascii() or not draft or not hmac.compare_digest(token, draft[0])
                or time.monotonic() >= draft[1]):
            raise ValueError("Review confirmation is invalid or expired.")
        self._verify(draft[2], draft[3], draft[4])
        with self._lock:
            if generation != self._generation or time.monotonic() >= draft[1]:
                raise ValueError("Review was cancelled or expired.")
