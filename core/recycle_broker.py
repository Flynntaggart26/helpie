"""Approval and result bookkeeping for a future Recycle Bin adapter.

This module does not itself touch files. No production adapter or API is wired
up yet: an adapter must independently verify the exact file at the operation
boundary, recycle it without permanent-delete fallback, and report only a
confirmed successful move. A review confirmation is never a recycle approval.
"""
from __future__ import annotations

import hmac
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

APPROVAL_SECONDS = 60.0
MAX_HISTORY = 100


@dataclass(frozen=True)
class RecycleCandidate:
    """An item and opaque snapshot supplied by trusted backend preflight."""

    display_path: str
    identity: bytes


class RecycleBroker:
    """Single-item, explicit, one-shot approval; no filesystem operations here."""

    def __init__(self, verify: Callable[[RecycleCandidate], bool],
                 recycle: Callable[[RecycleCandidate, threading.Event], bool] | None = None) -> None:
        self._verify = verify
        self._recycle = recycle
        self._lock = threading.Lock()
        self._draft = None
        self._generation = 0
        self._cancel_event = None
        self._history: list[str] = []

    def prepare(self, candidate: RecycleCandidate) -> str:
        if self._recycle is None:
            raise ValueError("Recycle operation is unavailable.")
        if (not isinstance(candidate, RecycleCandidate) or not isinstance(candidate.display_path, str)
                or not 1 <= len(candidate.display_path) <= 4096
                or not isinstance(candidate.identity, bytes) or not 1 <= len(candidate.identity) <= 256):
            raise ValueError("Invalid recycle candidate.")
        with self._lock:
            if self._cancel_event is not None:
                raise ValueError("A recycle operation is already in progress.")
            self._generation += 1
            generation = self._generation
            self._draft = None
        if self._verify(candidate) is not True:
            raise ValueError("The selected item could not be verified.")
        token = os.urandom(32).hex()
        with self._lock:
            if generation != self._generation:
                raise ValueError("The request was cancelled.")
            self._draft = (token, time.monotonic() + APPROVAL_SECONDS, candidate)
        return token

    def cancel(self) -> None:
        with self._lock:
            self._generation += 1
            self._draft = None
            if self._cancel_event is not None:
                self._cancel_event.set()

    def confirm(self, token: str, *, approved: bool) -> dict:
        """Consume approval once; only a verified successful move is listed."""
        with self._lock:
            draft = self._draft
            self._draft = None
            self._generation += 1
            if (approved is not True or not isinstance(token, str) or not token.isascii() or not draft
                    or not hmac.compare_digest(token, draft[0]) or time.monotonic() >= draft[1]
                    or self._recycle is None or self._cancel_event is not None):
                raise ValueError("Recycle approval is invalid, cancelled or expired.")
            cancel = threading.Event()
            self._cancel_event = cancel
        candidate = draft[2]
        try:
            if self._verify(candidate) is not True or cancel.is_set() or time.monotonic() >= draft[1]:
                raise ValueError("The item changed or the request expired.")
            # The adapter must revalidate under its own action-bound guard.
            recycled = self._recycle(candidate, cancel) is True
            if not recycled:
                return {"recycled": False, "items": []}
            with self._lock:
                self._history.append(candidate.display_path)
                self._history = self._history[-MAX_HISTORY:]
            return {"recycled": True, "items": [candidate.display_path]}
        finally:
            with self._lock:
                if self._cancel_event is cancel:
                    self._cancel_event = None

    def recent(self) -> list[str]:
        """Only moves reported successful by the adapter in this session."""
        with self._lock:
            return list(reversed(self._history))

    def available(self) -> bool:
        """True only when an actual recycle adapter has been configured."""
        return self._recycle is not None
