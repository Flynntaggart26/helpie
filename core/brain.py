"""The brain: fast rule engine first, then the LLM."""
from __future__ import annotations

import datetime as dt
import contextvars
import json
import math
import random
import re
import time
import threading
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import actions
import action_policy
import audit
import documents
import memory
import routines
import shutil
import updater
from llm import Brain as LlmBrain

GREETINGS = [
    "Hey! I'm here. What do you need?",
    "Hi there. Listening.",
    "Hello! What can I do for you?",
]

HELP_TEXT = (
    "I can open and close apps without stealing your focus, set volume and brightness, "
    "search the web, take notes, set reminders, read or write the clipboard, switch windows, "
    "do math, take screenshots, summarise documents, remember things about you, look at your "
    "screen and give you a morning briefing. You can chain commands with 'and then', like "
    "'open Chrome and search for cats'. Ask me anything else too and I will answer."
)

INTRO = (
    "I'm Helpie, your desktop assistant. I listen for your voice, run tasks on this "
    "computer and answer your questions out loud."
)

OPEN_VERBS = ("open", "launch", "start", "run", "aç", "başlat", "çalıştır")
CLOSE_VERBS = ("close", "quit", "kill", "stop", "kapat", "sonlandır")

STRONG_STEP_SEP = re.compile(
    r"\s*,?\s*(?:and then|then|after that|afterwards|sonra|ardından|ondan sonra)\s*", re.I)
WEAK_STEP_SEP = re.compile(r"\s+(and|ve)\s+", re.I)
WEAK_SPLIT_ONLY = re.compile(r"\s+(?:and|ve)\s+", re.I)
ACTION_WORDS = re.compile(
    r"\b(open|close|launch|start|run|search|google|look up|play|pause|resume|next|previous|"
    r"type|write|set|turn|lock|shut|restart|sleep|take|capture|screenshot|remind|timer|alarm|"
    r"add|read|copy|show|switch|focus|summari[sz]e|sum up|remember|forget|calculate|compute|"
    r"weather|brightness|volume|note|clipboard|briefing|read_screen|"
    r"what time|what day|what is the date|saat kaç|hangi gün|"
    r"aç|kapat|başlat|çalıştır|ara|çal|duraklat|yaz|ayarla|kıs|artır|azalt|kilitle|hatırlat|"
    r"not al|oku|kopyala|göster|geç|özetle|unutma|hatırla|hesapla|hava|ses|parlaklık|brifing)\b",
    re.I)
MAX_PLAN_STEPS = 4

FILLERS = re.compile(
    r"\b(helpie|please|just|hey|now|for me|can you|could you|would you|"
    r"lütfen|hemen|şimdi|bana|benim için|bir|acaba)\b", re.I
)

CONFIRM_YES = ("yes", "yeah", "yep", "sure", "do it", "confirm", "ok", "okay",
               "evet", "onayla", "onaylıyorum", "tamam", "doğru")
CONFIRM_NO = ("no", "nope", "cancel", "stop", "never mind", "don't",
              "hayır", "vazgeç", "iptal", "dur", "yok")

VISUAL_REQUEST_RE = re.compile(
    r"\b(?:point (?:to|at|out)|show me where|highlight|mark|circle|underline|"
    r"draw (?:an? )?(?:arrow|circle|box|rectangle))\b|"
    r"\b(?:işaretle|isaretle|vurgula|daire içine al|daire icine al|"
    r"ok çiz|ok ciz|okla göster|okla goster|altını çiz|altini ciz)\b",
    re.I,
)

SCREEN_REQUEST_RE = re.compile(
    r"\b(?:what(?:'s| is)? (?:on|in) my screen|what do you see on my screen|"
    r"read my screen|look at (?:my )?screen|describe (?:my |the )?screen|"
    r"explain (?:this|the) (?:error|screen)|what am i looking at|"
    r"read the screen|what is on the screen|what is on my display|"
    r"what(?:'s| is) on this screen)\b|"
    r"\b(?:ekranda ne var|ekranımda ne var|ekranimda ne var|"
    r"ekranımda ne görüyorsun|ekranimda ne goruyorsun|"
    r"ekranda ne görüyorsun|ekranda ne goruyorsun|"
    r"ekranıma bak|ekranima bak|ekrana bak|ekranı oku|ekrani oku|"
    r"ekranı (?:anlat|incele)|ekrani (?:anlat|incele)|"
    r"bu hatayı (?:açıkla|oku)|bu hatayi (?:acikla|oku))\b|"
    r"\b(?:point (?:to|at|out)|show me where|highlight|mark|circle|underline|"
    r"draw (?:an? )?(?:arrow|circle|box|rectangle)|"
    r"işaretle|isaretle|vurgula|daire içine al|daire icine al|"
    r"ok çiz|ok ciz|okla göster|okla goster|altını çiz|altini ciz)\b",
    re.I,
)

VISUAL_RESPONSE_MARKER = "[[HELPIE_VISUAL]]"
VISUAL_SCHEMA_VERSION = 1
GRAPH_TOKEN_RE = re.compile(
    r"(?P<space>\s+)|(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|"
    r"(?P<name>[A-Za-z]+)|(?P<operator>[+\-*/^()])"
)
GRAPH_FUNCTIONS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "sqrt": math.sqrt, "abs": abs, "ln": math.log, "log": math.log10,
    "exp": math.exp,
}


class _GraphExpressionParser:
    """Parse a small arithmetic grammar without Python eval or attribute access."""

    def __init__(self, source: str) -> None:
        if not isinstance(source, str) or not source.strip() or len(source) > 96:
            raise ValueError("Graph expression is empty or too long")
        self.tokens: list[tuple[str, str]] = []
        position = 0
        while position < len(source):
            match = GRAPH_TOKEN_RE.match(source, position)
            if not match:
                raise ValueError("Graph expression contains an unsupported character")
            position = match.end()
            kind = match.lastgroup
            if kind != "space":
                self.tokens.append((kind or "", match.group(kind or "")))
                if len(self.tokens) > 64:
                    raise ValueError("Graph expression is too complex")
        self.index = 0
        self.depth = 0

    def _peek(self, value: str | None = None) -> bool:
        if self.index >= len(self.tokens):
            return False
        return value is None or self.tokens[self.index][1] == value

    def _take(self) -> tuple[str, str]:
        if not self._peek():
            raise ValueError("Graph expression ended unexpectedly")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def parse(self) -> tuple:
        tree = self._sum()
        if self.index != len(self.tokens):
            raise ValueError("Graph expression has trailing tokens")
        return tree

    def _sum(self) -> tuple:
        node = self._product()
        while self._peek("+") or self._peek("-"):
            operator = self._take()[1]
            node = (operator, node, self._product())
        return node

    def _product(self) -> tuple:
        node = self._unary()
        while self._peek("*") or self._peek("/"):
            operator = self._take()[1]
            node = (operator, node, self._unary())
        return node

    def _unary(self) -> tuple:
        if self._peek("+") or self._peek("-"):
            operator = self._take()[1]
            return ("unary" + operator, self._unary())
        return self._power()

    def _power(self) -> tuple:
        node = self._primary()
        if self._peek("^"):
            self._take()
            node = ("^", node, self._unary())
        return node

    def _primary(self) -> tuple:
        kind, value = self._take()
        if kind == "number":
            number = float(value)
            if not math.isfinite(number) or abs(number) > 1e6:
                raise ValueError("Graph number is out of range")
            return ("number", number)
        if kind == "name":
            name = value.lower()
            if name == "x":
                return ("x",)
            if name in {"pi", "e"}:
                return ("number", math.pi if name == "pi" else math.e)
            if name not in GRAPH_FUNCTIONS or not self._peek("("):
                raise ValueError("Graph expression uses an unsupported name")
            self._take()
            return self._parenthesized(("function", name))
        if kind == "operator" and value == "(":
            return self._parenthesized()
        raise ValueError("Graph expression expected a number or x")

    def _parenthesized(self, prefix: tuple | None = None) -> tuple:
        self.depth += 1
        if self.depth > 16:
            raise ValueError("Graph expression nesting is too deep")
        try:
            node = self._sum()
            if not self._peek(")"):
                raise ValueError("Graph expression has an unclosed parenthesis")
            self._take()
            return (*prefix, node) if prefix else node
        finally:
            self.depth -= 1


def _eval_graph_expression(node: tuple, x: float) -> float:
    kind = node[0]
    if kind == "number":
        return node[1]
    if kind == "x":
        return x
    if kind == "unary+":
        return _eval_graph_expression(node[1], x)
    if kind == "unary-":
        return -_eval_graph_expression(node[1], x)
    if kind == "function":
        name, child = node[1], node[2]
        argument = _eval_graph_expression(child, x)
        if name == "exp" and not -20 <= argument <= 20:
            raise ValueError("Graph exponent is out of range")
        return GRAPH_FUNCTIONS[name](argument)
    left = _eval_graph_expression(node[1], x)
    right = _eval_graph_expression(node[2], x)
    if kind == "+":
        return left + right
    if kind == "-":
        return left - right
    if kind == "*":
        return left * right
    if kind == "/":
        if right == 0:
            raise ValueError("Graph expression divides by zero")
        return left / right
    if kind == "^":
        if abs(right) > 12:
            raise ValueError("Graph power is out of range")
        return left ** right
    raise ValueError("Graph expression contains an unsupported operation")


def _sample_graph(source: str) -> list[list[list[float]]]:
    """Return a bounded list of normalized polyline segments, or reject the graph."""
    tree = _GraphExpressionParser(source).parse()
    samples: list[tuple[float, float] | None] = []
    for index in range(65):
        x = -5.0 + 10.0 * index / 64
        try:
            y = _eval_graph_expression(tree, x)
            if isinstance(y, bool) or not isinstance(y, (int, float)):
                raise ValueError("Graph result is not a real number")
            if abs(y) > 1e6:
                raise ValueError("Graph result is out of range")
            y = float(y)
            if not math.isfinite(y):
                raise ValueError("Graph result is not finite")
        except (ArithmeticError, OverflowError, TypeError, ValueError):
            samples.append(None)
            continue
        samples.append((x, y))
    values = [sample[1] for sample in samples if sample is not None]
    if len(values) < 2:
        raise ValueError("Graph expression has too few finite points")
    low, high = min(values), max(values)
    if high - low < 1e-9:
        pad = max(1.0, abs(low) * 0.1)
        low -= pad
        high += pad
    else:
        pad = (high - low) * 0.05
        low -= pad
        high += pad
    span = high - low
    threshold = span * 0.65
    segments: list[list[list[float]]] = []
    current: list[list[float]] = []
    previous_y: float | None = None
    for index, sample in enumerate(samples):
        if sample is None or (previous_y is not None and abs(sample[1] - previous_y) > threshold):
            if len(current) >= 2:
                segments.append(current)
            current = []
        if sample is not None:
            current.append([index / 64, (high - sample[1]) / span])
            previous_y = sample[1]
        else:
            previous_y = None
    if len(current) >= 2:
        segments.append(current)
    if not segments:
        raise ValueError("Graph expression could not be plotted")
    return segments


def _parse_geometry(item: dict) -> tuple[list[dict], list[dict]] | None:
    """Validate a small geometry drawing and its references without solving it."""
    raw_objects = item.get("objects")
    raw_constraints = item.get("constraints", [])
    if (not isinstance(raw_objects, list) or not 1 <= len(raw_objects) <= 12
            or not isinstance(raw_constraints, list) or len(raw_constraints) > 8):
        return None

    def coord(value: object) -> Optional[float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            number = float(value)
        except OverflowError:
            return None
        return number if math.isfinite(number) and 0 <= number <= 1 else None

    objects: list[dict] = []
    for source in raw_objects:
        if not isinstance(source, dict):
            return None
        kind = source.get("kind")
        label = source.get("label", "")
        if not isinstance(label, str):
            return None
        label = re.sub(r"[\x00-\x1f\x7f]", "", label).strip()[:32]
        if kind == "point" and set(source) <= {"kind", "x", "y", "label"}:
            x, y = coord(source.get("x")), coord(source.get("y"))
            if x is None or y is None:
                return None
            objects.append({"kind": kind, "x": x, "y": y, "label": label})
        elif kind == "segment" and set(source) <= {
                "kind", "x1", "y1", "x2", "y2", "label"}:
            values = {key: coord(source.get(key)) for key in ("x1", "y1", "x2", "y2")}
            if any(value is None for value in values.values()) or (
                    values["x1"] == values["x2"] and values["y1"] == values["y2"]):
                return None
            objects.append({"kind": kind, **values, "label": label})
        elif kind == "circle" and set(source) <= {"kind", "cx", "cy", "radius", "label"}:
            cx, cy, radius = (coord(source.get(key)) for key in ("cx", "cy", "radius"))
            if (cx is None or cy is None or radius is None or radius <= 0
                    or cx - radius < 0 or cx + radius > 1
                    or cy - radius < 0 or cy + radius > 1):
                return None
            objects.append({"kind": kind, "cx": cx, "cy": cy,
                            "radius": radius, "label": label})
        elif kind == "polygon" and set(source) <= {"kind", "points", "label"}:
            raw_points = source.get("points")
            if not isinstance(raw_points, list) or not 3 <= len(raw_points) <= 8:
                return None
            points = []
            for point in raw_points:
                if not isinstance(point, list) or len(point) != 2:
                    return None
                px, py = coord(point[0]), coord(point[1])
                if px is None or py is None:
                    return None
                points.append([px, py])
            objects.append({"kind": kind, "points": points, "label": label})
        else:
            return None

    constraints: list[dict] = []
    for source in raw_constraints:
        if not isinstance(source, dict):
            return None
        kind = source.get("kind")
        if not isinstance(kind, str):
            return None
        refs = source.get("objects")
        expected = 1 if kind in {"horizontal", "vertical"} else 2
        if (kind not in {"horizontal", "vertical", "equal", "perpendicular", "parallel"}
                or set(source) != {"kind", "objects"}
                or not isinstance(refs, list) or len(refs) != expected
                or any(isinstance(ref, bool) or not isinstance(ref, int)
                       or not 0 <= ref < len(objects) or objects[ref]["kind"] != "segment"
                       for ref in refs)
                or len(set(refs)) != len(refs)):
            return None
        constraints.append({"kind": kind, "objects": refs})
    return objects, constraints


def _parse_visual_response(reply: str) -> tuple[str, list[dict]]:
    """Separate a model's optional visual proposal and accept only bounded shapes."""
    text, marker, raw = (reply or "").partition(VISUAL_RESPONSE_MARKER)
    if not marker:
        return (reply or "").strip(), []
    spoken = text.strip()
    try:
        payload = json.loads(raw.strip())
    except (TypeError, ValueError):
        return spoken, []
    if (not isinstance(payload, dict)
            or set(payload) != {"version", "items"}
            or isinstance(payload.get("version"), bool)
            or not isinstance(payload.get("version"), int)
            or payload.get("version") != VISUAL_SCHEMA_VERSION):
        return spoken, []
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 3:
        return spoken, []

    def coordinate(value: object) -> Optional[float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            number = float(value)
        except OverflowError:
            return None
        return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None

    accepted: list[dict] = []
    callout_numbers: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if not isinstance(kind, str):
            continue
        fields = {
            "pin": {"kind", "x", "y", "label"},
            "callout": {"kind", "x", "y", "number", "label"},
            "rect": {"kind", "x", "y", "width", "height", "label"},
            "arrow": {"kind", "x1", "y1", "x2", "y2", "label"},
            "equation": {"kind", "x", "y", "text"},
            "graph": {"kind", "x", "y", "width", "height", "expression"},
            "geometry": {"kind", "x", "y", "width", "height", "objects",
                         "constraints"},
        }.get(kind)
        if not fields or set(item) - (fields | {"explanation"}):
            continue
        parsed = {"kind": kind}
        explanation = item.get("explanation", "")
        if not isinstance(explanation, str) or len(explanation) > 160:
            continue
        explanation = explanation.strip()
        if explanation and (any(ord(c) < 32 for c in explanation) or explanation not in spoken):
            continue
        if explanation:
            parsed["explanation"] = explanation
        if kind == "equation":
            text_value = item.get("text")
            if not isinstance(text_value, str):
                continue
            text_value = re.sub(r"[\x00-\x1f\x7f]", "", text_value).strip()[:120]
            if not text_value:
                continue
            parsed["text"] = text_value
        elif kind == "graph":
            expression = item.get("expression")
            if not isinstance(expression, str):
                continue
            expression = expression.strip()
            try:
                segments = _sample_graph(expression)
            except (ArithmeticError, OverflowError, ValueError):
                continue
            parsed["expression"] = expression[:96]
            parsed["segments"] = segments
        elif kind == "geometry":
            geometry = _parse_geometry(item)
            if geometry is None:
                continue
            parsed["objects"], parsed["constraints"] = geometry
        else:
            label = item.get("label", "")
            if not isinstance(label, str):
                continue
            parsed["label"] = re.sub(r"[\x00-\x1f\x7f]", "", label).strip()[:60]
        if kind == "callout":
            number = item.get("number")
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 3:
                continue
            parsed["number"] = number
        keys = (("x", "y") if kind in {"pin", "callout", "equation"} else
                ("x", "y", "width", "height") if kind in {"rect", "graph", "geometry"} else
                ("x1", "y1", "x2", "y2"))
        values = {key: coordinate(item.get(key)) for key in keys}
        if any(value is None for value in values.values()):
            continue
        parsed.update(values)
        if kind in {"rect", "graph", "geometry"} and (
                parsed["width"] <= 0 or parsed["height"] <= 0
                or parsed["x"] + parsed["width"] > 1
                or parsed["y"] + parsed["height"] > 1):
            continue
        if kind == "arrow" and (parsed["x1"] == parsed["x2"]
                                and parsed["y1"] == parsed["y2"]):
            continue
        if kind == "callout":
            if parsed["number"] in callout_numbers:
                continue
            callout_numbers.add(parsed["number"])
        accepted.append(parsed)
    return spoken, accepted


def _norm(text: str) -> str:
    t = (text or "").lower().strip()
    t = t.replace("’", "'").replace("`", "'").replace("´", "'")
    return re.sub(r"\s+", " ", t)


def _clean_query(text: str) -> str:
    q = text
    q = re.sub(r"^(search|look up|find|google)\s+", "", q)
    q = re.sub(r"^(on |in )?(the )?(web|internet|google|youtube)\s+(for\s+)?", "", q)
    q = re.sub(r"\b(the web|the internet|internette|you ?tube'?da)\b", " ", q)
    q = re.sub(r"\b(com|net|org|from|please|for me|lütfen|bana|bir)\b", " ", q)
    q = re.sub(r"\b(search|look up|find|ara|araştır|bul|bak|bilgi ver|tell me)\b", " ", q)
    q = re.sub(r"\b(about|hakkında|ile ilgili)\b", " ", q)
    return re.sub(r"\s+", " ", q).strip(" ?!.,'\"")


WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "pazartesi": 0, "salı": 1, "sali": 1, "çarşamba": 2, "carsamba": 2,
    "perşembe": 3, "persembe": 3, "cuma": 4, "cumartesi": 5, "pazar": 6,
}


def _parse_repeat(text: str) -> Optional[tuple[str, int, int, Optional[int], int]]:
    """Find a repeating reminder schedule: (repeat, hour, minute, weekday, end)."""
    schedule: Optional[str] = None
    weekday: Optional[int] = None
    if re.search(r"\b(every\s+day|daily|each day|her\s+g[üu]n)\b", text):
        schedule = "daily"
    elif re.search(r"\b(every\s+weekday|weekdays|hafta\s+i[çc]i|her\s+hafta\s+i[çc]i)\b", text):
        schedule = "weekdays"
    else:
        match = re.search(r"\bevery\s+([a-zçğıöşü]+)\b|her\s+([a-zçğıöşü]+)\b", text)
        if match:
            name = (match.group(1) or match.group(2) or "").lower()
            if name in WEEKDAY_NAMES:
                schedule = "weekly"
                weekday = WEEKDAY_NAMES[name]
    if not schedule:
        return None

    clock = re.search(r"(?:\bat|\bsaat)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?", text)
    if not clock:
        clock = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if not clock:
        return None
    hour = int(clock.group(1))
    minute = int(clock.group(2) or 0)
    suffix = (clock.group(3) or "").lower()
    if suffix == "pm" and hour < 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return schedule, hour, minute, weekday, clock.end()


def _next_due(hour: int, minute: int, repeat: str, weekday: Optional[int] = None) -> dt.datetime:
    now = dt.datetime.now().replace(second=0, microsecond=0)
    target = now.replace(hour=hour, minute=minute)
    if target <= now:
        target += dt.timedelta(days=1)
    if repeat == "weekdays":
        while target.weekday() >= 5:
            target += dt.timedelta(days=1)
    elif repeat == "weekly" and weekday is not None:
        while target.weekday() != weekday:
            target += dt.timedelta(days=1)
    return target


def _reminder_label(text: str, start: int) -> str:
    tail = text[start:].strip(" ,.'\"")
    tail = re.sub(r"^'?d[ae]\b\s*", "", tail)
    tail = re.sub(r"^(to|that i (?:should|need to|have to)|i should|i need to|için|ki)\s+", "", tail)
    tail = re.sub(r"\b(remind me|reminder|hatırlatır mısın|hatırlat|kur|set)\b", " ", tail)
    tail = re.sub(r"(may[ıi]|meyi|mam[ıi]|memi)\s*$", "", tail)
    tail = re.sub(r"\s+", " ", tail).strip(" .,'\u2019")
    return tail or "your reminder"


def _parse_clock(text: str) -> Optional[tuple[dt.datetime, int]]:
    """One-off 'at 18:30' style time. Returns (due, end position)."""
    match = re.search(r"(?:\bat|\bsaat)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = (match.group(3) or "").lower()
    if suffix == "pm" and hour < 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return _next_due(hour, minute, "none"), match.end()


class Brain:
    """Understands text, performs the action, returns something to say."""

    def __init__(
        self,
        cfg: dict,
        on_speak: Optional[Callable[[str], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.cfg = cfg
        self.on_speak = on_speak or (lambda _text: None)
        self.on_quit = on_quit or (lambda: None)
        self.on_event = on_event or (lambda _event: None)
        self.llm = LlmBrain(cfg.get("api_key", ""), cfg.get("provider", "gemini"), cfg.get("model", ""))
        self.llm.configure(cfg)
        self.llm.memory_text = memory.as_prompt()
        self.pending: Optional[tuple[str, dict]] = None
        self._model_proposal: Optional[tuple[action_policy.ProposedAction, float]] = None
        self._model_proposal_lock = threading.Lock()
        self._model_proposal_generation = 0
        self._in_plan = False
        self._screen_capture_allowed = contextvars.ContextVar(
            "helpie_screen_capture_allowed", default=True,
        )
        self._screen_capture_source = contextvars.ContextVar(
            "helpie_screen_capture_source", default="chat",
        )
        self._explicit_screen_request = contextvars.ContextVar(
            "helpie_explicit_screen_request", default=False,
        )

    def refresh(self, cfg: dict) -> None:
        self.cfg = cfg
        self.llm.configure(cfg)
        self.llm.memory_text = memory.as_prompt()

    def _refresh_memory(self) -> None:
        self.llm.memory_text = memory.as_prompt()
        self.on_event({"type": "memory", "items": memory.list_items()})

    # ------------------------------------------------------------------ #
    def _resolve_folder(self, text: str) -> Optional[Path]:
        t = text.lower()
        mapping = {
            "desktop": Path.home() / "Desktop",
            "downloads": Path.home() / "Downloads",
            "documents": Path.home() / "Documents",
            "pictures": Path.home() / "Pictures",
            "music": Path.home() / "Music",
            "videos": Path.home() / "Videos",
            "masaüstü": Path.home() / "Desktop",
            "indirilenler": Path.home() / "Downloads",
            "belgeler": Path.home() / "Documents",
            "resimler": Path.home() / "Pictures",
            "müzik": Path.home() / "Music",
            "videolar": Path.home() / "Videos",
        }
        for key, path in mapping.items():
            if key in t:
                return path
        return None

    def _format_organize_result(self, result: dict, dry: bool) -> str:
        if "error" in result:
            return result["error"]
        prefix = "Preview: " if dry else ""
        if result["moved"] == 0:
            return f"{prefix}Nothing to organize in {Path(result['folder']).name}."
        lines = [f"{prefix}Organized {result['moved']} file(s) in {Path(result['folder']).name} by {result['by']}."]
        if result["errors"]:
            lines.append(f"  {result['errors']} error(s).")
        return " ".join(lines)

    def _format_organize_all_result(self, results: list[dict], dry: bool) -> str:
        prefix = "Preview: " if dry else ""
        total = sum(r.get("moved", 0) for r in results if "error" not in r)
        if total == 0:
            return f"{prefix}Nothing to organize."
        parts = [f"{prefix}Organized {total} file(s) across {len(results)} folder(s)."]
        for r in results:
            if "error" not in r and r.get("moved", 0):
                parts.append(f"  {Path(r['folder']).name}: {r['moved']} file(s)")
        return " ".join(parts)

    def _format_duplicate_result(self, result: dict, dry: bool) -> str:
        prefix = "Preview: " if dry else ""
        if result["groups"] == 0:
            return f"{prefix}No duplicate files found in {Path(result['folder']).name}."
        if result["removed"] == 0:
            return f"{prefix}Found {result['groups']} duplicate group(s) but removed none."
        freed_mb = result["freed_bytes"] / (1024 * 1024)
        return f"{prefix}Removed {result['removed']} duplicate file(s), freed {freed_mb:.1f} MB in {Path(result['folder']).name}."

    def _format_empty_folder_result(self, result: dict, dry: bool) -> str:
        prefix = "Preview: " if dry else ""
        if result["removed"] == 0:
            return f"{prefix}No empty folders found in {Path(result['folder']).name}."
        return f"{prefix}Removed {result['removed']} empty folder(s) in {Path(result['folder']).name}."

    # ------------------------------------------------------------------ #
    @staticmethod
    def _split_plan(text: str) -> list[str]:
        """Split 'open chrome and search for cats' into safe, actionable steps."""
        text = (text or "").strip()
        if not text or len(text) > 260:
            return [text] if text else []

        steps: list[str] = []
        for chunk in STRONG_STEP_SEP.split(text):
            chunk = chunk.strip(" ,.;")
            if not chunk:
                continue

            # "open chrome and spotify" -> ["open chrome", "open spotify"]
            match = re.match(r"(?i)^(open|launch|start|run|aç|başlat|çalıştır)\s+(.+)$", chunk)
            if match and WEAK_SPLIT_ONLY.search(match.group(2)):
                names = [n.strip(" ,.;") for n in WEAK_SPLIT_ONLY.split(match.group(2))]
                if len(names) > 1 and all(
                        0 < len(name.split()) <= 3 and not ACTION_WORDS.search(name)
                        for name in names):
                    steps.extend(f"{match.group(1)} {name}" for name in names)
                    continue

            tokens = WEAK_STEP_SEP.split(chunk)
            merged: list[str] = [tokens[0].strip(" ,.;")] if tokens[0].strip(" ,.;") else []
            for index in range(1, len(tokens), 2):
                separator = tokens[index].lower()
                piece = tokens[index + 1].strip(" ,.;") if index + 1 < len(tokens) else ""
                if not piece:
                    continue
                if merged and not ACTION_WORDS.search(piece):
                    merged[-1] = f"{merged[-1]} {separator} {piece}"
                else:
                    merged.append(piece)
            steps.extend(merged)

        steps = [step for step in steps if step]
        if len(steps) < 2:
            return [text]
        if sum(1 for step in steps if ACTION_WORDS.search(step)) < 2:
            return [text]
        return steps[:MAX_PLAN_STEPS]

    def _run_plan(self, steps: list[str]) -> str:
        steps = [str(step).strip(" ,.;") for step in (steps or []) if str(step).strip(" ,.;")]
        steps = steps[:MAX_PLAN_STEPS]
        if not steps or self._in_plan:
            return ""
        self._in_plan = True
        replies: list[str] = []
        try:
            for step in steps:
                try:
                    answer = self.handle(step)
                except Exception:
                    answer = ""
                if answer:
                    replies.append(answer)
                if self.pending:
                    break
        finally:
            self._in_plan = False
        return " ".join(replies) or "I could not run those steps."

    # ------------------------------------------------------------------ #
    def handle(self, text: str, allow_screen_capture: bool = True,
               source: str = "chat") -> str:
        token = self._screen_capture_allowed.set(bool(allow_screen_capture))
        source_token = self._screen_capture_source.set(source)
        explicit_token = self._explicit_screen_request.set(
            bool(SCREEN_REQUEST_RE.search(text)))
        try:
            return self._handle(text)
        finally:
            self._explicit_screen_request.reset(explicit_token)
            self._screen_capture_source.reset(source_token)
            self._screen_capture_allowed.reset(token)

    def cancel_model_proposal(self) -> None:
        with self._model_proposal_lock:
            had_proposal = self._model_proposal is not None
            self._model_proposal = None
            self._model_proposal_generation += 1
        if had_proposal:
            audit.log("Pending action cancelled", source="action")

    def _handle(self, text: str) -> str:
        with self._model_proposal_lock:
            proposal_generation = self._model_proposal_generation
        raw = (text or "").strip()
        if not raw:
            return "I didn't hear anything. Try again?"
        t = _norm(raw)
        alt = re.sub(r"\s+", " ", FILLERS.sub(" ", t)).strip()

        with self._model_proposal_lock:
            pending_proposal = self._model_proposal
            if pending_proposal and (time.monotonic() >= pending_proposal[1]
                                     or action_policy.confirmation(t) is not None):
                self._model_proposal = None
        if pending_proposal:
            proposal, deadline = pending_proposal
            if time.monotonic() >= deadline:
                audit.log("Pending action approval expired", ok=False, source="action")
                return "That action request expired. Please ask again."
            decision = action_policy.confirmation(t)
            if decision == "no":
                audit.log("Pending action cancelled", source="action")
                return "Okay, cancelled."
            if decision == "yes":
                audit.log("Pending action approved", source="action")
                if proposal.risk == "destructive":
                    return self._dispatch(proposal.name, proposal.args, confirmed=True)
                return self._dispatch(proposal.name, proposal.args)
            return f"Please say yes or no. Proposed action: {proposal.preview}."

        if self.pending:
            pending, self.pending = self.pending, None
            if action_policy.confirmation(t) == "yes":
                return self._dispatch(*pending, confirmed=True)
            if action_policy.confirmation(t) == "no":
                return "Okay, cancelled."
            self.pending = pending
            return "I need a yes or a no to continue."

        # Keep an explicit Helpie update request inside the trusted updater.
        # Otherwise it can fall through to the general assistant and be
        # misinterpreted as a filesystem or app-launch command.
        if re.search(
            r"\b(?:install|apply)\s+(?:(?:the|a)\s+)?(?:(?:new|latest)\s+)?"
            r"(?:helpie\s+)?update\b|\bupdate\s+helpie\b|"
            r"\bhelpie(?:'s)?\s+update\b|"
            r"\b(?:helpie(?:'yi|yi)?\s+güncelle|(?:yeni\s+)?güncellemeyi\s+(?:yükle|kur))\b",
            t,
        ):
            release = updater.check()
            if not release.get("available"):
                if release.get("error"):
                    audit.log("Checked Helpie update", ok=False)
                    return f"I could not check for updates. {release['error']}"
                audit.log("Checked Helpie update", ok=True)
                version = release.get("current") or updater.current_version()
                return f"Helpie {version} is already up to date."
            result = updater.apply(str(release.get("url", "")), release=release)
            return str(result.get("message", "The update could not be started."))

        if not self._in_plan:
            # Don't split routine commands into plans
            if not re.search(r"\b(save routine|create routine|new routine|run routine|execute routine|delete routine|remove routine)\b", t):
                steps = self._split_plan(raw)
                if len(steps) > 1:
                    return self._run_plan(steps)

        if re.fullmatch(r"(?:close|close helpie|helpie close|kapat|helpie(?:'yi|yi)? kapat)[!.? ]*", t):
            audit.log("Closed Helpie")
            self.on_quit()
            return "Closing Helpie."

        if re.search(r"\b(quit|exit|goodbye|good bye|see you|shut yourself down|"
                     r"kendini kapat|görüşürüz|helpie kapan)\b", t):
            self.on_quit()
            return "See you! Open Helpie again whenever you need me."

        if re.fullmatch(r"(good morning|morning|günaydın)[!. ]*", t) or \
                re.search(r"\b(morning briefing|daily briefing|brief me|briefing|"
                          r"günlük brifing|güne başla)\b", t):
            return actions.briefing(self.cfg.get("city", ""))

        if re.fullmatch(r"(hi|hello|hey|yo|good morning|good afternoon|good evening|"
                        r"merhaba|selam|selamlar|günaydın)[!. ]*", t):
            return random.choice(GREETINGS)
        if re.search(r"\b(who are you|your name|what are you|introduce yourself|"
                     r"sen kimsin|adın ne|kimsin)\b", t):
            return INTRO
        if re.search(r"\b(what can you do|help me|show commands|commands|abilities|"
                     r"ne yapabilirsin|yardım)\b", t):
            return HELP_TEXT

        # memory
        if re.search(r"\b(what do you (remember|know) about me|what do you remember|"
                     r"benim hakkımda ne (hatırlıyorsun|biliyorsun)|hafızanda ne var|"
                     r"ne hatırlıyorsun)\b", t):
            return memory.memory_summary()
        if re.search(r"\b(forget (everything|all|it all|me)|clear (your )?memory|"
                     r"wipe (your )?memory|hafızayı (temizle|sil)|her şeyi unut|unut beni)\b", t):
            count = memory.clear()
            self._refresh_memory()
            return f"Memory cleared. I forgot {count} thing{'s' if count != 1 else ''}."
        match = re.search(r"^(?:please\s+)?(?:forget(?: that)?|unut)\s+(.+)$", raw, re.I)
        if match:
            removed = memory.remove(match.group(1))
            self._refresh_memory()
            return "Forgotten." if removed else "I could not find that in my memory."
        match = re.search(r"^(?:please\s+)?(?:remember(?: that)?|keep in mind that|"
                          r"don'?t forget that)\s+(.+)$", raw, re.I)
        if not match:
            match = re.search(r"^(?:hatırla|unutma|aklında tut)[:\s]+(.+)$", raw, re.I)
        if not match:
            match = re.search(r"^(.+?)\s+(?:unutma|aklında tut|hatırla)$", raw, re.I)
        if match:
            item = memory.add(match.group(1))
            self._refresh_memory()
            return memory.remember_reply(item)

        # what is on the screen
        if (self._screen_capture_source.get() == "companion"
                and re.search(
                    r"\b(?:clear|remove|hide) (?:all )?(?:the )?(?:highlights?|annotations?|markers?)\b|"
                    r"\b(?:vurguları|işaretleri|işaretlemeleri) temizle\b", t)):
            self.on_event({"type": "visual_annotations", "items": [], "duration_ms": 0})
            return "I cleared the screen highlights."
        if SCREEN_REQUEST_RE.search(t):
            return self._describe_screen(raw)

        # document summaries
        match = re.search(r"^(?:please\s+)?(?:summari[sz]e|sum up|give me a summary of)\s+"
                          r"(?:the\s+)?(?:document\s+|file\s+|pdf\s+|word\s+)?(.+)$", t)
        if not match:
            match = re.search(r"^(.+?)\s+(?:dosyasını|dosyayı|belgeyi)?\s*özetle$", t)
        if match:
            return documents.summarize(match.group(1).strip(), self.llm)

        # --- Routines (must be before time/weather to catch "save routine ... what time is it") ---
        if re.search(r"\b(save routine|create routine|new routine)\b", t):
            match = re.search(r"(?:save|create|new)\s+routine\s+(\w+)\s+(?:with\s+steps?\s+)?(.+)", t, re.I)
            if match:
                name = match.group(1)
                steps_text = match.group(2).strip()
                step_parts = re.split(r"\s+(?:and\s+then|then|after\s+that|sonra)\s+", steps_text, flags=re.I)
                steps = []
                for part in step_parts:
                    part = part.strip()
                    if not part:
                        continue
                    # Map natural language to handler names
                    action_map = {
                        "open": "open_app",
                        "close": "close_app",
                        "launch": "open_app",
                        "what": "what_time",  # custom handler for time
                        "time": "what_time",
                        "search": "web_search",
                        "google": "web_search",
                        "youtube": "web_search",
                        "volume": "volume",
                        "brightness": "brightness",
                        "screenshot": "screenshot",
                        "lock": "lock_screen",
                        "sleep": "sleep",
                        "shutdown": "power",
                        "restart": "power",
                        "note": "add_note",
                        "remind": "set_timer",
                        "calculate": "calculate",
                    }
                    action_match = re.match(r"(\w+)\s+(.+)", part)
                    if action_match:
                        action, args_str = action_match.groups()
                        handler_name = action_map.get(action.lower(), action.lower())
                        if handler_name == "what_time":
                            steps.append({"action": "what_time", "args": {"text": args_str}})
                        elif handler_name in ("open_app", "close_app", "launch"):
                            steps.append({"action": "open_app" if handler_name in ("open_app", "launch") else "close_app", "args": {"app": args_str}})
                        elif handler_name == "volume":
                            steps.append({"action": "volume", "args": {"direction": args_str}})
                        elif handler_name == "brightness":
                            steps.append({"action": "brightness", "args": {"direction": args_str}})
                        elif handler_name == "web_search":
                            steps.append({"action": "web_search", "args": {"query": args_str}})
                        else:
                            steps.append({"action": handler_name, "args": {"text": args_str}})
                    else:
                        steps.append({"action": part, "args": {}})
                if steps:
                    routines.save_routine(match.group(1), steps, f"Created from voice: {steps_text}")
                    return f"Routine '{match.group(1)}' saved with {len(steps)} step(s)."

        # Parse params from "with params key=value, key=value"
        def _extract_params(text):
            params = {}
            # Match "with params key=value, key=value" or "params key=value"
            param_match = re.search(r"\b(?:with\s+)?params?\s+(.+)$", text, re.I)
            if param_match:
                param_str = param_match.group(1)
                # Split by comma or "and"
                for pair in re.split(r"\s*,\s*|\s+and\s+", param_str):
                    pair = pair.strip()
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        params[key.strip()] = value.strip()
            return params

        if re.search(r"\b(run routine|execute routine)\b", t):
            match = re.search(r"(?:run|execute)\s+routine\s+(\w+)", t)
            if match:
                params = _extract_params(t)
                return self._run_routine(match.group(1), params)
        # Also support "run <routine_name>" as shorthand
        if re.search(r"^run\s+\w+", t):
            match = re.search(r"^run\s+(\w+)", t)
            if match:
                params = _extract_params(t)
                return self._run_routine(match.group(1), params)

        if re.search(r"\b(delete routine|remove routine)\b", t):
            match = re.search(r"(?:delete|remove)\s+routine\s+(\w+)", t)
            if match:
                return self._delete_routine(match.group(1))

        if re.search(r"\b(list routines?|show routines?|my routines?)\b", t):
            return self._list_routines()

        if re.search(r"\b(what time|the time|time is it|saat kaç)\b", t):
            return actions.now_time()
        if re.search(r"\b(what day|the date|today's date|which day|tarih|hangi gün)\b", t):
            return actions.now_date()

        if re.search(r"\b(weather|temperature|forecast|hava durumu|hava nasıl)\b", t):
            return actions.weather(self.cfg.get("city", ""))

        if re.search(r"\bbattery\b|\bcharge level\b|\bpil\b", t) and \
                re.search(r"(status|level|percent|how much|durum|kaç)", t):
            return actions.battery()
        if re.search(r"\b(cpu|ram|memory|system)\b", t) and \
                re.search(r"(usage|load|status|how much|kullanım|durum)", t):
            return actions.system_info()

        # volume
        match = re.search(r"(?:volume|ses)\s*(?:to|at|seviyesini|seviyesi)?\s*(?:%|yüzde)?\s*(\d{1,3})", t)
        if match:
            return actions.set_volume(int(match.group(1)))
        if re.search(r"\b(mute|sessize al|sustur|sessiz)\b", t):
            return actions.volume("mute")
        if re.search(r"\b(unmute|turn (the )?volume up|volume up|louder|sesi aç|sesi artır)\b", t):
            return actions.volume("up")
        if re.search(r"\b(turn (the )?volume down|volume down|quieter|lower the volume|sesi kıs|sesi azalt)\b", t):
            return actions.volume("down")

        # brightness
        match = re.search(r"brightness\s*(?:to|at)?\s*(\d{1,3})", t)
        if match:
            return actions.set_brightness(int(match.group(1)))
        if re.search(r"(increase|raise|up)\s+(the\s+)?brightness|parlakl[ıi][ğg][ıi]\s*(artır|yükselt)", t):
            return actions.brightness("up")
        if re.search(r"(decrease|lower|reduce|dim)\s+(the\s+)?(brightness|screen)|parlakl[ıi][ğg][ıi]\s*(kıs|azalt)", t):
            return actions.brightness("down")

        # media
        if re.search(r"\b(pause|stop) (the )?(music|video|playback)\b|\bmüziği durdur\b", t):
            return actions.media("pause")
        if re.search(r"\b(play|resume) (the )?(music|video)\b|\bmüziği (çal|oynat)\b", t):
            return actions.media("play")
        if re.search(r"\b(next (track|song))|sonraki (şarkı|parça)\b", t):
            return actions.media("next")
        if re.search(r"\b(previous|last) (track|song)|önceki (şarkı|parça)\b", t):
            return actions.media("prev")

        if re.search(r"\b(screenshot|screen shot|screen capture|capture the screen|ekran görüntüsü)\b", t):
            return actions.screenshot()

        if re.search(r"\b(lock (the )?(screen|pc|computer)|kilitle)\b", t) and "shut" not in t:
            return actions.lock_screen()

        if re.search(r"\b(shut ?down|turn off (the )?(pc|computer)|power off|bilgisayarı kapat)\b", t):
            self.pending = ("power", {"mode": "shutdown"})
            return "I am about to shut the computer down. Are you sure?"
        if re.search(r"\b(restart|reboot|yeniden başlat)\b", t):
            self.pending = ("power", {"mode": "restart"})
            return "I am about to restart the computer. Are you sure?"
        if re.search(r"\b(sleep|suspend)\b", t) and re.search(r"(pc|computer|bilgisayar)", t):
            self.pending = ("power", {"mode": "sleep"})
            return "I am about to put the computer to sleep. Are you sure?"
        if re.search(r"\b(cancel (the )?(shutdown|restart)|kapanmayı iptal)\b", t):
            return actions.cancel_shutdown()

        if re.search(r"recycle bin|geri dönüşüm", t) and re.search(r"(empty|clear|boşalt|temizle)", t):
            if self._in_plan:
                audit.log("Blocked destructive action in a plan", ok=False, source="action")
                return "Please request emptying the Recycle Bin separately so I can ask for confirmation."
            proposal = action_policy.review_direct_action("empty_recycle_bin", {})
            with self._model_proposal_lock:
                if proposal_generation != self._model_proposal_generation:
                    return "The action request was cancelled."
                if self._model_proposal is not None:
                    return "Another action is awaiting confirmation. Please answer yes or no."
                self._model_proposal = (proposal, time.monotonic() + 60.0)
            audit.log("Requested destructive action approval", source="action")
            return f"Proposed action: {proposal.preview}. Say yes to confirm or no to cancel."

        # notes
        match = re.search(r"(?:take a note|make a note|note that|add a note|not al)[:\s]+(.+)$", t)
        if match:
            return actions.add_note(match.group(1).strip())
        if re.search(r"\b(read|show|list)\b.*\bnotes\b|\bnotlarımı (oku|göster)\b", t):
            return actions.read_notes()
        if re.search(r"\b(clear|delete|erase)\b.*\bnotes\b|\bnotlarımı sil\b", t):
            return actions.clear_notes()

        # clipboard
        if re.search(r"\bclipboard\b|\bpanoda\b|\bpanoyu\b|\bpanoya\b", t):
            reading = re.search(r"(read|show|what'?s? (?:on|in)|what is (?:on|in)|oku|göster|ne var)", t)
            writing = re.search(r"(copy|write|put|add|kopyala|yaz)", t)
            if reading and not writing:
                return actions.read_clipboard()
            match = re.search(
                r"(?:copy|put|write|add)\s+(.+?)\s+(?:to|into|in|on)\s+(?:the\s+|my\s+)?clipboard", t)
            if not match:
                match = re.search(
                    r"(?:copy|write|add|put)\s+(?:this\s+)?(?:to\s+|into\s+)?(?:the\s+|my\s+)?clipboard[:\s]+(.+)$", t)
            if not match:
                match = re.search(r"(.+?)\s+(?:panoya|panoyu)\s*(?:kopyala|yaz)", t)
            if match:
                return actions.write_clipboard(match.group(1).strip())
            return actions.read_clipboard()

        # windows
        if re.search(r"\b(show (?:the )?desktop|minimize everything|minimize all|masaüstünü göster)\b", t):
            return actions.show_desktop()
        if re.search(r"\b(list|show|what)\b.*\bwindows\b|\bopen windows\b|\baçık pencereler\b", t):
            return actions.window_titles()
        match = re.search(r"^(?:switch to|focus|activate|bring up|go to the)\s+(?:the\s+)?(.+?)(?:\s+window)?$", t)
        if match:
            return self._dispatch_direct_desktop("switch_window", {"name": match.group(1)})
        match = re.search(r"^(.+?)(?:'?[ae])?\s+(?:penceresine|penceresini)?\s*(?:geç|getir)$", t)
        if match:
            return self._dispatch_direct_desktop("switch_window", {"name": match.group(1)})

        # reminders (repeating or absolute time)
        schedule_match = _parse_repeat(t)
        if schedule_match and re.search(r"(remind|reminder|timer|alarm|hatırlat|hatırlatıcı)", t):
            schedule, hour, minute, weekday, end = schedule_match
            due = _next_due(hour, minute, schedule, weekday)
            return actions.add_reminder(_reminder_label(t, end), due, schedule)
        if re.search(r"(remind|reminder|hatırlat)", t):
            clock = _parse_clock(t)
            if clock:
                due, end = clock
                return actions.add_reminder(_reminder_label(t, end), due, "none")
        if re.search(r"\b(show|list|read|what are)\b.*\breminders?\b"
                     r"|\bhatırlatıcılar[ıi]m[ıi]?\b|\bhatırlatıcıları (göster|oku)\b", t):
            return actions.read_reminders()
        if re.search(r"\b(clear|delete|cancel|remove)\b.*\breminders?\b"
                     r"|\bhatırlatıcıları (sil|temizle)\b", t):
            return actions.clear_reminders()

        # timers
        match = re.search(
            r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|saniye|dakika|saat)\b(.*)", t)
        if match and re.search(r"(remind|reminder|timer|alarm|hatırlat|kur)", t):
            amount = float(match.group(1))
            unit = match.group(2)
            factor = 1 if unit.startswith(("sec", "saniye")) else 60 if unit.startswith(("min", "dakika")) else 3600
            label = match.group(3)
            label = re.sub(r"^(to|için|sonra)\s+", "", label.strip())
            label = re.sub(r"\b(remind|reminder|timer|alarm|hatırlat|kur|set|me)\b", " ", label)
            return actions.set_timer(amount * factor, re.sub(r"\s+", " ", label).strip(), self.on_speak)

        if re.search(r"\b(calculate|compute|how much is|what is|what's|hesapla|kaç eder)\b", t) and re.search(r"\d", t):
            return actions.calculate(t)
        if re.fullmatch(r"[\d\s+\-*/().,%]+", t):
            return actions.calculate(t)

        match = re.search(r"^(?:type|write|yaz)[:\s]+(.+)$", t)
        if match:
            return actions.type_text(match.group(1))

        # files
        match = re.search(r"(?:open|find|aç)\s+(?:the\s+)?(?:file\s+)?(.+?)\s*(?:file|dosyasını|dosyayı)?$", t)
        if match and re.search(r"(file|dosya)", t):
            return actions.open_file(re.sub(r"\bfile\b|\bdosya\b", "", match.group(1)).strip())
        match = re.search(r"open\s+(?:the\s+)?(desktop|downloads|documents|pictures|music|videos)"
                          r"|(masaüstü|indirilenler|belgeler|resimler|müzik|videolar)\s*(?:klasörünü|klasörü)?\s*aç", t)
        if match:
            return actions.open_folder(match.group(1) or match.group(2))

        # file organizer
        if re.search(r"\b(organize|sort|arrange|clean up|tidy|düzenle|sırala|temizle)\b", t) and \
           re.search(r"\b(desktop|downloads|documents|folder|klasör|masaüstü|indirilenler|belgeler)\b", t):
            folder = self._resolve_folder(t)
            if folder:
                by = "date" if re.search(r"\b(date|tarih|time)\b", t) else "type"
                dry = bool(re.search(r"\b(dry|preview|test|simulate|önizleme)\b", t))
                result = actions.organize_folder(folder, by, dry)
                return self._format_organize_result(result, dry)
            return "Which folder should I organize? Try 'organize downloads by type'."

        if re.search(r"\b(organize|sort|arrange|clean up|tidy|düzenle|sırala|temizle)\b", t) and \
           re.search(r"\b(all|everything|hepsi|her yer)\b", t):
            by = "date" if re.search(r"\b(date|tarih|time)\b", t) else "type"
            dry = bool(re.search(r"\b(dry|preview|test|simulate|önizleme)\b", t))
            results = actions.organize_all(by, dry)
            return self._format_organize_all_result(results, dry)

        if re.search(r"\b(duplicate|duplicates|copy|copies|kopyalar|tekrar)\b", t) and \
           re.search(r"\b(find|remove|delete|clean|bul|sil|temizle)\b", t):
            folder = self._resolve_folder(t) or Path.home() / "Downloads"
            dry = bool(re.search(r"\b(dry|preview|test|simulate|önizleme)\b", t))
            result = actions.remove_duplicates(folder, dry)
            return self._format_duplicate_result(result, dry)

        if re.search(r"\b(empty folder|empty folders|boş klasör|boş klasörler)\b", t) and \
           re.search(r"\b(remove|delete|clean|sil|temizle)\b", t):
            folder = self._resolve_folder(t) or Path.home() / "Downloads"
            dry = bool(re.search(r"\b(dry|preview|test|simulate|önizleme)\b", t))
            result = actions.clean_empty_folders(folder, dry)
            return self._format_empty_folder_result(result, dry)

        # --- Email & Calendar ---
        if re.search(r"\b(read emails?|check emails?|show emails?|what emails?)\b", t):
            return self._dispatch_plugin_command("read email")
        if re.search(r"\b(send emails?|send mail|email to)\b", t):
            return self._dispatch_plugin_command("send email")
        if re.search(r"\b(calendar|upcoming events|my schedule|what meetings|ajanda|toplantılarım)\b", t):
            return self._dispatch_plugin_command("calendar")
        if re.search(r"\b(create event|schedule meeting|add to calendar)\b", t):
            return self._dispatch_plugin_command("create event")

        site_key = next((s for s in actions.SITES if s in t), None)
        if site_key and re.search(r"\b(open|go to|launch|aç|git|gir)\b", t):
            return actions.open_site(site_key)

        app_key = actions.resolve_app(alt)
        if app_key and any(verb in t for verb in CLOSE_VERBS):
            return self._dispatch_direct_desktop("close_app", {"app": app_key})
        if app_key and any(verb in t for verb in OPEN_VERBS):
            return self._dispatch_direct_desktop("open_app", {"app": app_key})
        match = re.search(r"^(?:open|launch|start|run|aç|başlat|çalıştır)\s+(.+)$", alt)
        if match and not re.search(r"(file|dosya|folder|klasör|volume|ses|brightness|parlaklık)", match.group(1)):
            return self._dispatch_direct_desktop("open_app", {"app": match.group(1)})

        # search
        match = re.search(r"^(?:youtube|yt)\s+(.{2,})$", t)
        if match:
            return actions.web_search(match.group(1), "youtube")
        if re.search(r"\b(search|look up|google|ara|araştır)\b", t) or re.search(r"(hakkında|about)", t):
            engine = "youtube" if "youtube" in t else "google"
            query = _clean_query(t)
            if len(query) > 1:
                return actions.web_search(query, engine)

        match = re.search(r"(https?://\S+|www\.\S+)", t)
        if match:
            return actions.open_url(match.group(1))

        # --- Plugin commands (before LLM fallback) ---
        plugin_result = self._dispatch_plugin_command(t)
        if plugin_result:
            return plugin_result

        if self.llm.available:
            reply = self.llm.chat(raw)
            if reply:
                cleaned, action = self._extract_action(reply)
                if action:
                    if self._in_plan:
                        audit.log("Blocked model action in a plan", ok=False, source="action")
                        return "I cannot run a model-proposed action inside a plan. Please ask for one action."
                    proposal = action_policy.review_model_action(*action)
                    if proposal is None:
                        audit.log("Blocked unsupported model action", ok=False, source="action")
                        return "I cannot perform that proposed action. Please request a supported action directly."
                    with self._model_proposal_lock:
                        if proposal_generation != self._model_proposal_generation:
                            return "The action request was cancelled."
                        if self._model_proposal and time.monotonic() >= self._model_proposal[1]:
                            self._model_proposal = None
                        if self._model_proposal is not None:
                            return "Another action is awaiting confirmation. Please answer yes or no."
                        self._model_proposal = (proposal, time.monotonic() + 60.0)
                    audit.log("Requested model action approval", source="action")
                    return f"Proposed action: {proposal.preview}. Say yes to confirm or no to cancel."
                return cleaned or reply
            if getattr(self.llm, "last_error", ""):
                return self.llm.last_error

        if re.search(r"\b(open|close|set|start|stop|turn|delete|show)\b", t):
            return "Sorry, I did not understand that. Could you rephrase it?"
        if not self.llm.available:
            return ("Local features (time, weather, open apps, notes, reminders, "
                    "calculations) work without a model. To chat and ask questions, "
                    "add a provider in Settings (Ctrl+H -> Settings -> AI Providers).")
        return "Sorry, something went wrong while answering."

    # ------------------------------------------------------------------ #
    def _describe_screen(self, prompt: str) -> str:
        if not self._screen_capture_allowed.get():
            return "Screen reading is unavailable for this request. Open Helpie chat to choose a screen capture."
        if not self.cfg.get("screen_context_consent", False):
            if self._screen_capture_source.get() == "companion":
                return ("Screen access is off. In Settings → Voice, enable both full-chat screen access "
                        "and local live view for the Ctrl+H companion.")
            return ("Screen reading is off. Turn it on in Settings "
                    "(Settings → Voice → Allow full chat to read your screen).")
        if (self._screen_capture_source.get() == "companion"
                and not self.cfg.get("companion_live_view_consent", False)):
            return ("Local live screen view is off. Enable it in Settings before asking the "
                    "Ctrl+H companion to read your screen.")
        if not self.llm.available:
            return ("Screen reading needs a configured AI provider in Settings "
                    "(Ctrl+H -> Settings -> AI Providers).")
        self.on_event({"type": "state", "value": "capturing"})
        source = self._screen_capture_source.get()
        if source == "companion":
            if not self._explicit_screen_request.get():
                return 'Ask directly, for example: “What is on my screen?” I only send a frame after that request.'
            try:
                import shell
                capture = shell.capture_latest_frame(timeout=3.0)
                if capture:
                    session = shell.live_capture_status(timeout=1.0)
                    if not session or not session.get("active") or not session.get("companion_active"):
                        capture = None
            except Exception:
                capture = None
            if capture:
                image, metadata = capture
                try:
                    captured_ms = int(metadata.get("captured_at_ms", ""))
                    captured_at = dt.datetime.fromtimestamp(
                        captured_ms / 1000, tz=dt.timezone.utc,
                    ).astimezone().isoformat(timespec="seconds")
                except (TypeError, ValueError, OSError, OverflowError):
                    captured_at = "unknown"
                metadata = {
                    "captured_at": captured_at,
                    "target": metadata.get("target") or "Primary display",
                    "active_window": "not available",
                }
        else:
            capture = actions.capture_screen_context()
        if not capture:
            self.on_event({"type": "state", "value": "thinking"})
            if source == "companion":
                return ("I could not get a fresh desktop frame. Check that screen reading is enabled, "
                        "the companion is open, and Windows allows screen capture, then try again.")
            return "I could not capture the screen."
        image, metadata = capture
        self.on_event({"type": "state", "value": "thinking"})
        capture_context = (
            f"Capture time: {metadata['captured_at']}. Target: {metadata['target']}. "
            f"Window context: {metadata['active_window'] or 'not available'}.\n\n"
        )
        remote = True
        if self.llm.provider == "ollama":
            endpoint = str(self.cfg.get("ollama_url", "http://localhost:11434"))
            remote = urlparse(endpoint).hostname not in {"localhost", "127.0.0.1", "::1"}
        elif self.llm.provider == "openai":
            endpoint = str(self.cfg.get("openai_url", ""))
            remote = urlparse(endpoint).hostname not in {"localhost", "127.0.0.1", "::1"}
        self.on_event({"type": "screen_frame_transfer", "active": True, "remote": remote})
        answer = None
        annotate = source == "companion" and bool(VISUAL_REQUEST_RE.search(prompt or ""))
        try:
            answer = self.llm.vision(
                capture_context + (prompt or "What is on my screen right now?"), image,
                annotate=annotate,
            )
        finally:
            self.on_event({"type": "screen_frame_transfer", "active": False, "remote": False})
            if source == "companion":
                audit.log(
                    "Requested companion screen analysis from "
                    + ("a remote AI provider" if remote else "a local AI provider"),
                    metadata["target"], ok=bool(answer), source="screen",
                )
        if not answer:
            return ("I could not read the screen with this model. Check that the selected model "
                    "supports images and that the provider is reachable.")
        if annotate:
            answer, items = _parse_visual_response(answer)
            if items:
                try:
                    import shell
                    session = shell.live_capture_status(timeout=0.5)
                except Exception:
                    session = None
                if session and session.get("active") and session.get("companion_active"):
                    self.on_event({"type": "visual_annotations", "items": items,
                                   "duration_ms": 12000})
        return answer

    @staticmethod
    def _extract_action(reply: str) -> tuple[str, Optional[tuple[str, dict]]]:
        match = re.search(r"\[\[ACTION\]\]\s*(\{.*?\})\s*$", reply, re.S)
        if not match:
            return reply.strip(), None
        try:
            payload = json.loads(match.group(1))
            name = str(payload.get("name", "")).strip()
            if name:
                return reply[: match.start()].strip(), (name, payload.get("args") or {})
        except (json.JSONDecodeError, AttributeError):
            pass
        return reply.strip(), None

    @staticmethod
    def _audit_entry(name: str, args: dict) -> tuple[str, str, str]:
        """Human readable (title, detail, source) for the audit log, or empty strings."""
        text = str(args.get("app") or args.get("text") or args.get("name")
                   or args.get("query") or args.get("url") or "").strip()
        mapping = {
            "remember": ("Remembered a fact", text, "action"),
            "read_screen": ("Looked at the screen", str(args.get("prompt", "")), "action"),
            "summarize_file": ("Summarised a document", text, "action"),
            "run_routine": ("Ran routine", text, "routine"),
            "save_routine": ("Saved routine", text, "routine"),
            "delete_routine": ("Deleted routine", text, "routine"),
        }
        entry = mapping.get(name)
        if not entry:
            return ("", "", "")
        return entry

    def _dispatch_direct_desktop(self, name: str, args: dict) -> str:
        proposal = action_policy.review_direct_action(name, args)
        if proposal is None:
            audit.log("Blocked invalid desktop action", ok=False, source="action")
            return "I could not use that application or window name."
        return self._dispatch(proposal.name, proposal.args)

    def _dispatch(self, name: str, args: dict, confirmed: bool = False) -> str:
        if name == "empty_recycle_bin":
            if not confirmed or args != {}:
                audit.log("Blocked unconfirmed destructive action", ok=False, source="action")
                return "Please request emptying the Recycle Bin directly and confirm it."
            return actions.empty_recycle_bin()
        if name == "power":
            mode = str(args.get("mode", "shutdown")).lower()
            if mode not in {"shutdown", "restart", "sleep"}:
                return "I cannot perform that power action."
            if not confirmed:
                self.pending = ("power", {"mode": mode})
                labels = {"shutdown": "shut the computer down", "restart": "restart the computer",
                          "sleep": "put the computer to sleep"}
                return f"I am about to {labels[mode]}. Are you sure?"
            return self._power(mode)
        try:
            minutes = float(args.get("minutes", 0) or 0)
        except (TypeError, ValueError):
            minutes = 0.0

        handlers: dict[str, Callable[[dict], str]] = {
            "open_app": lambda a: actions.open_app(str(a.get("app", ""))),
            "close_app": lambda a: actions.close_app(str(a.get("app", ""))),
            "web_search": lambda a: actions.web_search(str(a.get("query", "")), str(a.get("engine", "google"))),
            "open_site": lambda a: actions.open_site(str(a.get("name", ""))),
            "open_url": lambda a: actions.open_url(str(a.get("url", ""))),
            "set_volume": lambda a: actions.set_volume(float(a.get("percent", 50))),
            "volume": lambda a: actions.volume(str(a.get("direction", "up"))),
            "set_brightness": lambda a: actions.set_brightness(int(a.get("percent", 50))),
            "add_note": lambda a: actions.add_note(str(a.get("text", ""))),
            "type_text": lambda a: actions.type_text(str(a.get("text", ""))),
            "screenshot": lambda a: actions.screenshot(),
            "set_timer": lambda a: actions.set_timer(minutes * 60, str(a.get("label", "")), self.on_speak),
            "set_reminder": lambda a: actions.set_timer(minutes * 60, str(a.get("label", "")), self.on_speak),
            "read_clipboard": lambda a: actions.read_clipboard(),
            "write_clipboard": lambda a: actions.write_clipboard(str(a.get("text", ""))),
            "switch_window": lambda a: actions.switch_window(str(a.get("name", ""))),
            "show_desktop": lambda a: actions.show_desktop(),
            "read_reminders": lambda a: actions.read_reminders(),
            "lock_screen": lambda a: actions.lock_screen(),
            "calculate": lambda a: actions.calculate(str(a.get("expression", ""))),
            "weather": lambda a: actions.weather(self.cfg.get("city", "")),
            "battery": lambda a: actions.battery(),
            "system_info": lambda a: actions.system_info(),
            "remember": lambda a: self._remember(str(a.get("text", ""))),
            "read_screen": lambda a: self._describe_screen(str(a.get("prompt", ""))),
            "summarize_file": lambda a: documents.summarize(str(a.get("query", "")), self.llm),
            "briefing": lambda a: actions.briefing(self.cfg.get("city", "")),
            "plan": lambda a: self._run_plan(a.get("steps") or []),
            "what_time": lambda a: actions.now_time(),
            "plan": lambda a: self._run_plan(a.get("steps") or []),
            "run_routine": lambda a: self._run_routine(a.get("name", ""), a.get("params", {})),
            "save_routine": lambda a: self._save_routine(a.get("name", ""), a.get("steps", []), a.get("description", "")),
            "delete_routine": lambda a: self._delete_routine(a.get("name", "")),
            "list_routines": lambda a: self._list_routines(),
        }
        handler = handlers.get(name)
        if not handler:
            return ""
        title, detail, source = self._audit_entry(name, args)
        try:
            result = handler(args)
        except Exception:
            if title:
                audit.log(title, detail, ok=False, source=source)
            return "Something went wrong while doing that."
        if title:
            audit.log(title, detail, source=source)
        return result

    def _remember(self, text: str) -> str:
        item = memory.add(text)
        self._refresh_memory()
        return memory.remember_reply(item)

    def _dispatch_plugin_command(self, text: str) -> str:
        """Check if any enabled plugin has a command matching the input."""
        try:
            # Get plugins from the app (if available)
            if not hasattr(self, '_app') or not self._app:
                return ""
            plugins = self._app.plugins
            if not plugins:
                return ""
            for plugin in plugins.plugins.values():
                if not plugin.enabled or not plugin.instance:
                    continue
                # Check if plugin has get_commands method
                if hasattr(plugin._api, 'get_commands'):
                    commands = plugin._api.get_commands()
                    for cmd_name, cmd_info in commands.items():
                        patterns = cmd_info.get("patterns", [])
                        for pattern in patterns:
                            if re.search(pattern, text, re.I):
                                # Found matching pattern, call the handler
                                handler = cmd_info.get("handler")
                                if handler and callable(handler):
                                    # handler is a bound method, call with args keyword
                                    try:
                                        result = handler(args={})
                                    except TypeError:
                                        # Fallback for handlers that don't accept args
                                        result = handler()
                                    audit.log("Ran plugin command", f"{cmd_name} · {text}", source="plugin")
                                    return result
        except Exception:
            pass
        return ""

    @staticmethod
    def _power(mode: str) -> str:
        if mode == "restart":
            return actions.shutdown_pc(restart=True)
        if mode == "sleep":
            return actions.sleep_pc()
        return actions.shutdown_pc()

    def _run_routine(self, name: str, params: dict = None) -> str:
        if not hasattr(self, '_app') or not self._app:
            return "Routines not available."
        routine = routines.get_routine(name)
        if routine and any(step.get("action") == "power" for step in routine.get("steps", [])):
            return "Power actions must be requested directly so Helpie can confirm them first."
        return routines.run_routine(name, params, executor=self._execute_routine_step)

    def _execute_routine_step(self, step_name: str, step_args: dict) -> str:
        # Reuse the existing _dispatch for routine steps
        return self._dispatch(step_name, step_args)

    def _save_routine(self, name: str, steps: list, description: str = "") -> str:
        if not name:
            return "Routine name required."
        if not steps:
            return "At least one step required."
        if routines.save_routine(name, steps, description):
            return f"Routine '{name}' saved."
        return "Failed to save routine."

    def _delete_routine(self, name: str) -> str:
        if not name:
            return "Routine name required."
        if routines.delete_routine(name):
            return f"Routine '{name}' deleted."
        return f"Routine '{name}' not found."

    def _list_routines(self) -> str:
        items = routines.list_routines()
        if not items:
            return "No routines saved. Say 'save routine ...' to create one."
        lines = ["📋 Saved routines:"]
        for r in items:
            lines.append(f"  • {r['name']}: {r['description']} ({len(r['steps'])} steps)")
        return "\n".join(lines)

    def summary(self) -> str:
        now = dt.datetime.now()
        who = self.cfg.get("user_name") or "there"
        return (f"Hi {who}. It is {now.hour:02d}:{now.minute:02d}. "
                "Press Control H any time you want to talk, or type below.")
