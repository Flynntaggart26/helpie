"""Short-lived, one-use approval for a narrow set of UI data actions."""
from __future__ import annotations

import hmac
import secrets
import threading
import time

import action_policy

ALLOWED_ACTIONS = frozenset({"clear_memory", "forget_memory", "delete_routine"})
APPROVAL_SECONDS = 60.0


class ApprovalDrafts:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._draft = None

    def prepare(self, name: object, args: object) -> tuple[str, str]:
        if not isinstance(name, str) or name not in ALLOWED_ACTIONS:
            raise ValueError("Unsupported action.")
        proposal = action_policy.review_direct_action(name, args)
        if proposal is None:
            raise ValueError("Invalid action target.")
        token = secrets.token_hex(32)
        with self._lock:
            self._draft = (token, time.monotonic() + APPROVAL_SECONDS, proposal)
        return token, proposal.preview

    def consume(self, token: object) -> action_policy.ProposedAction:
        with self._lock:
            draft = self._draft
            self._draft = None
            if (not draft or not isinstance(token, str) or not token.isascii()
                    or not hmac.compare_digest(token, draft[0]) or time.monotonic() >= draft[1]):
                raise ValueError("Approval is invalid, cancelled or expired.")
            return draft[2]

    def cancel(self, token: object = None) -> None:
        with self._lock:
            if token is None or (self._draft and isinstance(token, str) and token.isascii()
                                 and hmac.compare_digest(token, self._draft[0])):
                self._draft = None
