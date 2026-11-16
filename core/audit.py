"""Privacy-conscious audit log of action types and outcomes.

Stored as JSON Lines in ``data/audit.jsonl`` so the newest entry is always the last
line and the file is safe to append to from several threads. Caller-provided
details are intentionally omitted because they may contain private user content.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

import config

LOG_FILE = config.DATA_DIR / "audit.jsonl"
MAX_ENTRIES = 500
ROTATE_AT = 800

_lock = threading.RLock()


def _entry(action: str, detail: str, ok: bool, source: str) -> dict:
    has_detail = bool(str(detail or "").strip())
    return {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "action": str(action)[:120],
        "detail": "Details withheld for privacy" if has_detail else "",
        "ok": bool(ok),
        "source": source,
    }


def log(action: str, detail: str = "", ok: bool = True, source: str = "action") -> None:
    """Append one entry. Never raises: logging must not break a command."""
    try:
        entry = _entry(action, detail, ok, source)
        line = json.dumps(entry, ensure_ascii=False)
        with _lock:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            if _count_unlocked() > ROTATE_AT:
                _trim_unlocked()
    except Exception:
        pass


def _count_unlocked() -> int:
    try:
        with LOG_FILE.open("r", encoding="utf-8") as handle:
            return sum(1 for _ in handle)
    except FileNotFoundError:
        return 0


def _trim_unlocked() -> None:
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    if len(lines) <= MAX_ENTRIES:
        return
    try:
        LOG_FILE.write_text("\n".join(lines[-MAX_ENTRIES:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def tail(limit: int = 200, source: str = "") -> list[dict]:
    """Newest entries first."""
    try:
        with _lock:
            try:
                lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                return []
    except Exception:
        return []

    entries = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if source and entry.get("source") != source:
            continue
        entries.append(entry)
        if len(entries) >= max(1, min(int(limit), 1000)):
            break
    return entries


def clear() -> bool:
    try:
        with _lock:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            LOG_FILE.write_text("", encoding="utf-8")
        return True
    except Exception:
        return False


def stats() -> dict:
    entries = tail(1000)
    by_source: dict[str, int] = {}
    for entry in entries:
        key = entry.get("source", "action")
        by_source[key] = by_source.get(key, 0) + 1
    return {"count": len(entries), "by_source": by_source}
