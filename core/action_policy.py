"""Bounded review of model-proposed desktop actions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProposedAction:
    name: str
    args: dict[str, Any]
    preview: str


def review_model_action(name: str, args: object) -> ProposedAction | None:
    """Accept only simple, single actions with complete, printable targets."""
    fields = {"open_app": ("app", "Open app"), "close_app": ("app", "Close app"),
              "switch_window": ("name", "Switch to window")}
    spec = fields.get(name)
    if spec is None or not isinstance(args, dict) or set(args) != {spec[0]}:
        return None
    value = args[spec[0]]
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return ProposedAction(name=name, args={spec[0]: value}, preview=f"{spec[1]}: {value}")


def confirmation(text: str) -> str | None:
    normalized = text.strip().lower().strip(" .!?…")
    if normalized in {"yes", "yeah", "yep", "sure", "do it", "confirm", "ok", "okay",
                      "evet", "onayla", "onaylıyorum", "tamam", "doğru"}:
        return "yes"
    if normalized in {"no", "nope", "cancel", "stop", "never mind", "don't",
                      "hayır", "hayir", "vazgeç", "vazgec", "iptal", "dur", "yok"}:
        return "no"
    return None
