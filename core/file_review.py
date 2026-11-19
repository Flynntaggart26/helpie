"""Bounded read-only inventory for duplicate files and empty folders."""
from __future__ import annotations

import hashlib
import os
import stat
import time
from pathlib import Path

MAX_ENTRIES = 2000
MAX_RESULTS = 100
MAX_HASH_BYTES = 128 * 1024 * 1024
MAX_SECONDS = 8.0


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


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
                empty.append(folder.relative_to(root).as_posix())
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
        rows = [{"path": path} for path in sorted(empty)[:MAX_RESULTS]]
        return {"root": str(root), "kind": kind, "items": rows,
                "limited": limited or len(empty) > MAX_RESULTS}
    groups: dict[int, list[tuple[Path, os.stat_result]]] = {}
    for path, info in files:
        groups.setdefault(info.st_size, []).append((path, info))
    hashes: dict[tuple[int, str], list[tuple[str, int, int]]] = {}
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
                    if _is_link(opened) or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
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
                    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) or time.monotonic() >= deadline:
                        limited = True
                        continue
                hashes.setdefault((size, digest.hexdigest()), []).append(
                    (path.relative_to(root).as_posix(), before.st_dev, before.st_ino))
            except OSError:
                limited = True
    rows = []
    for (size, _digest), entries in hashes.items():
        entries.sort()
        unique = []
        identities = set()
        for path, device, inode in entries:
            if (device, inode) not in identities:
                identities.add((device, inode))
                unique.append(path)
        if len(unique) > 1:
            rows.extend({"path": path, "matches": unique[0], "size": size} for path in unique[1:])
    rows.sort(key=lambda item: item["path"])
    return {"root": str(root), "kind": kind, "items": rows[:MAX_RESULTS],
            "limited": limited or len(rows) > MAX_RESULTS}
