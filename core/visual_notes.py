"""Local, bounded storage for editable visual notes (vector strokes only)."""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import threading
import uuid

import config

NOTES_FILE = config.DATA_DIR / "visual_notes.json"
MAX_NOTES = 100
MAX_STROKES = 200
MAX_POINTS_PER_STROKE = 500
MAX_POINTS_TOTAL = 10_000
MAX_TITLE_LENGTH = 120
MAX_STORE_BYTES = 5_000_000
ALLOWED_COLORS = {"#55d6ff", "#f59e0b", "#f472b6", "#f8fafc"}
_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_lock = threading.RLock()


def _read_unlocked() -> list[dict]:
    try:
        if NOTES_FILE.stat().st_size > MAX_STORE_BYTES:
            raise ValueError("Visual note storage is too large.")
    except FileNotFoundError:
        return []
    try:
        raw = NOTES_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("Visual note storage is invalid.")
    notes = []
    seen_ids: set[str] = set()
    for item in payload:
        if (not isinstance(item, dict) or set(item) != {"id", "title", "updated_at", "strokes"}
                or not isinstance(item.get("id"), str) or not _ID_RE.fullmatch(item["id"])
                or item["id"] in seen_ids
                or not isinstance(item.get("title"), str) or not item["title"].strip()
                or len(item["title"]) > MAX_TITLE_LENGTH
                or any(ord(char) < 32 for char in item["title"])
                or not isinstance(item.get("updated_at"), str)
                or len(item["updated_at"]) > 40):
            raise ValueError("Visual note storage contains an invalid note.")
        seen_ids.add(item["id"])
        notes.append({"id": item["id"], "title": item["title"],
                      "updated_at": item["updated_at"],
                      "strokes": _normalize_strokes(item["strokes"])})
    return notes


def _write_unlocked(items: list[dict]) -> None:
    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = NOTES_FILE.with_suffix(".json.tmp")
    encoded = json.dumps(items, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_STORE_BYTES:
        raise ValueError("Visual notes reached the local storage limit. Delete an old note first.")
    temporary.write_bytes(encoded)
    temporary.replace(NOTES_FILE)


def _normalize_strokes(value: object) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_STROKES:
        raise ValueError("A visual note can contain up to 200 strokes.")
    result: list[dict] = []
    point_count = 0
    for stroke in value:
        if not isinstance(stroke, dict) or set(stroke) != {"color", "size", "points"}:
            raise ValueError("A stroke has an invalid format.")
        color = stroke["color"]
        size = stroke["size"]
        points = stroke["points"]
        if not isinstance(color, str) or color not in ALLOWED_COLORS:
            raise ValueError("A stroke uses an unsupported color.")
        if isinstance(size, bool) or not isinstance(size, (int, float)) or not 1 <= size <= 20:
            raise ValueError("A stroke size is out of range.")
        if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS_PER_STROKE:
            raise ValueError("A stroke has too many points.")
        point_count += len(points)
        if point_count > MAX_POINTS_TOTAL:
            raise ValueError("A visual note has too many points.")
        clean_points: list[dict[str, float]] = []
        for point in points:
            if not isinstance(point, dict) or set(point) != {"x", "y"}:
                raise ValueError("A point has an invalid format.")
            x, y = point["x"], point["y"]
            if any(isinstance(number, bool) or not isinstance(number, (int, float))
                   or not math.isfinite(number) or not 0 <= number <= 1 for number in (x, y)):
                raise ValueError("A point is outside the note canvas.")
            clean_points.append({"x": float(x), "y": float(y)})
        result.append({"color": color, "size": float(size), "points": clean_points})
    return result


def list_notes() -> list[dict]:
    with _lock:
        notes = _read_unlocked()
        return [{"id": note["id"], "title": note["title"], "updated_at": note["updated_at"],
                 "stroke_count": len(note["strokes"])} for note in reversed(notes)]


def get_note(note_id: str) -> dict | None:
    if not _ID_RE.fullmatch(note_id or ""):
        return None
    with _lock:
        return next((dict(note) for note in _read_unlocked() if note["id"] == note_id), None)


def save_note(note_id: str, title: str, strokes: object) -> dict:
    if not isinstance(title, str):
        raise ValueError("Enter a title up to 120 characters.")
    title = title.strip()
    if not title or len(title) > MAX_TITLE_LENGTH or any(ord(char) < 32 for char in title):
        raise ValueError("Enter a title up to 120 characters.")
    clean_strokes = _normalize_strokes(strokes)
    now = dt.datetime.now().astimezone().isoformat(timespec="minutes")
    with _lock:
        notes = _read_unlocked()
        existing = None
        if note_id:
            if not _ID_RE.fullmatch(note_id):
                raise ValueError("The visual note ID is invalid.")
            existing = next((note for note in notes if note["id"] == note_id), None)
            if existing is None:
                raise ValueError("That visual note no longer exists.")
        elif len(notes) >= MAX_NOTES:
            raise ValueError("Helpie can keep up to 100 visual notes. Delete one to make room.")
        note = {"id": existing["id"] if existing else uuid.uuid4().hex,
                "title": title, "updated_at": now, "strokes": clean_strokes}
        if existing:
            notes[notes.index(existing)] = note
        else:
            notes.append(note)
        _write_unlocked(notes)
        return dict(note)


def delete_note(note_id: str) -> bool:
    if not _ID_RE.fullmatch(note_id or ""):
        raise ValueError("The visual note ID is invalid.")
    with _lock:
        notes = _read_unlocked()
        remaining = [note for note in notes if note["id"] != note_id]
        if len(remaining) == len(notes):
            return False
        _write_unlocked(remaining)
        return True
