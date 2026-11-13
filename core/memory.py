"""Long-term memory: small facts Helpie keeps about the user."""
from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Optional

import config

_lock = threading.RLock()
MAX_ITEMS = 200


def _path() -> Path:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR / "memory.json"


def _read() -> list[dict]:
    path = _path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and str(item.get("text", "")).strip()]


def _write(items: list[dict]) -> None:
    _path().write_text(json.dumps(items[-MAX_ITEMS:], ensure_ascii=False, indent=2), encoding="utf-8")


def _clean(text: str) -> str:
    text = " ".join(str(text or "").split()).strip()
    return text.strip(" .;,")


def add(text: str, kind: str = "fact") -> Optional[dict]:
    text = _clean(text)
    if not text:
        return None
    with _lock:
        items = _read()
        lowered = text.lower()
        for item in items:
            if str(item.get("text", "")).lower() == lowered:
                return item
        item = {
            "text": text,
            "kind": kind or "fact",
            "time": dt.datetime.now().isoformat(timespec="minutes"),
        }
        items.append(item)
        _write(items)
    return item


def list_items() -> list[dict]:
    with _lock:
        return list(reversed(_read()))


def remove(text: str) -> bool:
    target = _clean(text).lower()
    if not target:
        return False
    with _lock:
        items = _read()
        kept = [item for item in items if str(item.get("text", "")).lower() != target]
        if len(kept) == len(items):
            kept = [item for item in items if target not in str(item.get("text", "")).lower()]
        if len(kept) == len(items):
            return False
        _write(kept)
    return True


def clear() -> int:
    with _lock:
        items = _read()
        _write([])
    return len(items)


def as_prompt(max_items: int = 40) -> str:
    items = list_items()[:max_items]
    if not items:
        return ""
    lines = "\n".join(f"- {item['text']}" for item in items)
    return f"Things you remember about the user (use them naturally, never list them unprompted):\n{lines}"


def remember_reply(item: Optional[dict]) -> str:
    if not item:
        return "I did not catch what I should remember."
    return "Got it. I will remember that."


def memory_summary() -> str:
    items = list_items()
    if not items:
        return "I do not remember anything about you yet. Say 'remember that ...' and I will keep it."
    recent = items[:6]
    return "Here is what I remember: " + " | ".join(item["text"] for item in recent) + "."
