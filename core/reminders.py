"""Persistent reminders: one-off timers and repeating reminders.

Stored in data/reminders.json so they survive a restart. A small scheduler
thread checks every few seconds and fires due items through a callback.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
import uuid
from typing import Callable, Optional

import config
import notify

PATH = config.DATA_DIR / "reminders.json"
REPEATS = ("none", "daily", "weekdays", "weekly")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
TURKISH_WEEKDAYS = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def _iso(value: dt.datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _parse(value: str) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


class ReminderStore:
    def __init__(self, on_fire: Optional[Callable[[dict], None]] = None) -> None:
        self.on_fire = on_fire
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self.items: list[dict] = self._load()

    # -- storage -------------------------------------------------------- #
    def _load(self) -> list[dict]:
        try:
            raw = json.loads(PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        items = []
        for item in raw if isinstance(raw, list) else []:
            due = _parse(item.get("due", ""))
            if not due or not item.get("text"):
                continue
            repeat = item.get("repeat") if item.get("repeat") in REPEATS else "none"
            items.append({
                "id": str(item.get("id") or uuid.uuid4().hex[:8]),
                "text": str(item["text"]),
                "due": _iso(due),
                "repeat": repeat,
                "created": str(item.get("created") or _iso(_now())),
            })
        return items

    def _save(self) -> None:
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            PATH.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # -- public API ----------------------------------------------------- #
    def add(self, text: str, due: dt.datetime, repeat: str = "none") -> dict:
        text = (text or "").strip() or "Timer"
        repeat = repeat if repeat in REPEATS else "none"
        item = {
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "due": _iso(due),
            "repeat": repeat,
            "created": _iso(_now()),
        }
        with self._lock:
            self.items.append(item)
            self._save()
        return item

    def add_in(self, seconds: float, text: str, repeat: str = "none") -> dict:
        return self.add(text, _now() + dt.timedelta(seconds=max(1.0, float(seconds))), repeat)

    def list(self) -> list[dict]:
        with self._lock:
            return sorted(self.items, key=lambda item: item["due"])

    def remove(self, reminder_id: str) -> bool:
        with self._lock:
            before = len(self.items)
            self.items = [item for item in self.items if item["id"] != reminder_id]
            removed = len(self.items) != before
            if removed:
                self._save()
            return removed

    def clear(self) -> int:
        with self._lock:
            count = len(self.items)
            self.items = []
            self._save()
            return count

    # -- scheduler ------------------------------------------------------ #
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                self._tick()
            except Exception:
                pass
            time.sleep(5)

    def _tick(self) -> None:
        now = _now()
        due_now: list[dict] = []
        with self._lock:
            keep: list[dict] = []
            for item in self.items:
                when = _parse(item["due"])
                if when is None or when > now:
                    keep.append(item)
                    continue
                due_now.append(dict(item))
                if item["repeat"] == "none":
                    continue
                nxt = self._next(item, when, now)
                keep.append({**item, "due": _iso(nxt)})
            if due_now:
                self.items = keep
                self._save()
        for item in due_now:
            self._notify(item)
            if self.on_fire:
                try:
                    self.on_fire(item)
                except Exception:
                    pass

    @staticmethod
    def _next(item: dict, when: dt.datetime, now: dt.datetime) -> dt.datetime:
        repeat = item.get("repeat", "none")
        step = dt.timedelta(days=7 if repeat == "weekly" else 1)
        nxt = when + step
        guard = 0
        while nxt <= now and guard < 400:
            nxt += step
            guard += 1
        if repeat == "weekdays":
            while nxt.weekday() >= 5:
                nxt += dt.timedelta(days=1)
        return nxt

    @staticmethod
    def _notify(item: dict) -> None:
        try:
            notify.toast("Helpie reminder", item.get("text", "Reminder"))
        except Exception:
            pass


# One shared store for the whole app.
store = ReminderStore()
