"""Local web server + JSON API for the Helpie UI."""
from __future__ import annotations

import itertools
import json
import mimetypes
import os
import socket
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import actions
import config
import updater
from brain import Brain
from voice import Listener, Speaker, list_microphones

ROOT = config.APP_DIR
UI_DIR = ROOT / "ui"

VOICES = [
    {"id": "en-US-AriaNeural", "label": "Aria — English (US, female)"},
    {"id": "en-US-GuyNeural", "label": "Guy — English (US, male)"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia — English (UK)"},
    {"id": "tr-TR-EmelNeural", "label": "Emel — Turkish"},
    {"id": "tr-TR-AhmetNeural", "label": "Ahmet — Turkish"},
]

LANGUAGES = [
    {"id": "en-US", "label": "English (US)"},
    {"id": "en-GB", "label": "English (UK)"},
    {"id": "tr-TR", "label": "Turkish"},
]


# --------------------------------------------------------------------------- #
#  Event bus (UI polls this)
# --------------------------------------------------------------------------- #
class EventBus:
    def __init__(self) -> None:
        self._items: list[dict] = []
        self._lock = threading.Lock()
        self._seq = itertools.count(1)

    def push(self, event: dict) -> int:
        with self._lock:
            event_id = next(self._seq)
            self._items.append({"id": event_id, **event})
            if len(self._items) > 400:
                self._items = self._items[-250:]
            return event_id

    def since(self, after: int) -> list[dict]:
        with self._lock:
            return [item for item in self._items if item["id"] > after]


# --------------------------------------------------------------------------- #
#  Application
# --------------------------------------------------------------------------- #
class App:
    def __init__(self) -> None:
        self.cfg = config.load()
        self.bus = EventBus()
        self.state = "idle"
        self._listen_lock = threading.Lock()
        self._listening = False
        self._closing = False
        self._speaking = False
        self._turn = 0
        self.server: Optional[ThreadingHTTPServer] = None

        self.speaker = Speaker(
            voice=self.cfg["voice"],
            rate=self.cfg["rate"],
            volume=self.cfg["volume"],
            on_start=self._on_speak_start,
            on_end=self._on_speak_end,
        )
        self.listener = Listener()
        self.brain = Brain(self.cfg, on_speak=self._speak, on_quit=self.shutdown,
                           on_event=self.bus.push)

    # -- events ---------------------------------------------------------- #
    def push(self, event: dict) -> None:
        self.bus.push(event)

    def push_state(self, state: str, detail: str = "") -> None:
        self.state = state
        self.bus.push({"type": "state", "value": state, "detail": detail})

    def _on_speak_start(self) -> None:
        self._speaking = True
        self.push_state("speaking")

    def _on_speak_end(self) -> None:
        self._speaking = False
        if not self._listening:
            self.push_state("idle")

    def _speak(self, text: str) -> None:
        self.speaker.say(text)

    # -- conversation ---------------------------------------------------- #
    def reply(self, user_text: str) -> str:
        self.bus.push({"type": "message", "role": "user", "text": user_text})
        self.push_state("thinking")
        try:
            answer = self.brain.handle(user_text)
        except Exception:
            traceback.print_exc()
            answer = "Something went wrong on my side, but I'm still here."
        self.bus.push({"type": "message", "role": "assistant", "text": answer})
        self.speaker.say(answer)
        return answer

    def listen(self, reason: str = "manual") -> None:
        if not self._listen_lock.acquire(blocking=False):
            return
        try:
            self._listening = True
            self._turn = 0
            while not self._closing:
                self.push_state("listening")
                started = time.time()
                loudest = 0.0
                last_push = 0.0

                def on_level(value: float) -> None:
                    nonlocal last_push, loudest
                    loudest = max(loudest, value)
                    now = time.time()
                    if now - last_push > 0.08:
                        last_push = now
                        self.bus.push({"type": "level", "value": round(value, 3)})

                wav = self.listener.listen(
                    mic_index=self.cfg.get("mic_index"),
                    on_level=on_level,
                    on_speech=lambda: self.push_state("hearing"),
                )
                if self._closing:
                    break

                if not wav:
                    if loudest < 0.02 and time.time() - started > 3:
                        self.bus.push({"type": "hint", "text":
                                       "No sound reached the microphone. Check that it is on and unmuted."})
                    self.push_state("idle")
                    break

                self.push_state("thinking", "transcribing…")
                try:
                    text = self.listener.transcribe(wav, self.cfg.get("language", "en-US"))
                except Exception as exc:
                    self.push_state("idle")
                    self.bus.push({"type": "error",
                                   "text": f"Speech recognition failed ({type(exc).__name__}). Check your connection."})
                    break

                if not text:
                    self.push_state("idle")
                    self.bus.push({"type": "hint", "text": "I could not make out what you said."})
                    break

                self.bus.push({"type": "heard", "text": text})
                self._listening = False
                self.reply(text)
                self.speaker.wait_idle(60)
                self._listening = True

                if not (self.cfg.get("continuous") and reason == "auto"):
                    break
                self._turn += 1
                if self._turn >= int(self.cfg.get("auto_turns", 3)):
                    break

            self._listening = False
            self.push_state("idle")
        finally:
            self._listening = False
            self._listen_lock.release()

    def listen_async(self, reason: str = "manual") -> None:
        if self._listen_lock.locked():
            return
        threading.Thread(target=self.listen, args=(reason,), daemon=True).start()

    # -- settings -------------------------------------------------------- #
    def public_cfg(self) -> dict:
        safe = {k: v for k, v in self.cfg.items() if k != "api_key"}
        safe["has_key"] = bool(self.cfg.get("api_key"))
        safe["key_hint"] = ("•" * 6 + self.cfg["api_key"][-4:]) if self.cfg.get("api_key") else ""
        return safe

    def update_settings(self, patch: dict) -> dict:
        allowed = {"user_name", "provider", "api_key", "model", "voice", "rate", "volume",
                   "mic_index", "language", "auto_listen", "continuous", "auto_turns",
                   "city", "check_updates"}
        for key, value in (patch or {}).items():
            if key in allowed:
                self.cfg[key] = value
        config.save(self.cfg)
        self.brain.refresh(self.cfg)
        self.speaker.update(self.cfg.get("voice"), self.cfg.get("rate"), self.cfg.get("volume"))
        self.bus.push({"type": "settings", "value": self.public_cfg()})
        return self.public_cfg()

    # -- lifecycle ------------------------------------------------------- #
    def shutdown(self) -> None:
        self._closing = True
        try:
            self.speaker.close()
        except Exception:
            pass
        try:
            import keyboard

            keyboard.unhook_all()
        except Exception:
            pass
        threading.Timer(0.3, lambda: os._exit(0)).start()


# --------------------------------------------------------------------------- #
#  HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    app: App

    server_version = "Helpie/1.0"

    def log_message(self, fmt: str, *args) -> None:  # keep the console clean
        return

    # -- helpers --------------------------------------------------------- #
    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, data: dict, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return {}

    def _static(self, path: str) -> None:
        relative = path.lstrip("/") or "index.html"
        target = (UI_DIR / relative).resolve()
        if not str(target).startswith(str(UI_DIR.resolve())) or not target.is_file():
            self._json({"error": "not found"}, 404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix in {".html", ".css", ".js"}:
            content_type += "; charset=utf-8"
        self._send(200, target.read_bytes(), content_type)

    # -- routes ---------------------------------------------------------- #
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        app = self.app

        if path.startswith("/api/"):
            if path == "/api/init":
                self._json({
                    "settings": app.public_cfg(),
                    "mics": list_microphones(),
                    "voices": VOICES,
                    "languages": LANGUAGES,
                    "version": updater.current_version(),
                    "state": app.state,
                })
                return
            if path == "/api/events":
                after = int(query.get("after", ["0"])[0] or 0)
                self._json({"events": app.bus.since(after)})
                return
            if path == "/api/notes":
                self._json({"notes": list(reversed(actions.notes_list()))})
                return
            if path == "/api/update/check":
                self._json(updater.check())
                return
            if path == "/api/health":
                self._json({"ok": True, "version": updater.current_version()})
                return
            self._json({"error": "unknown endpoint"}, 404)
            return

        self._static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._body()
        app = self.app

        if path == "/api/ask":
            text = str(body.get("text", "")).strip()
            answer = app.reply(text)
            self._json({"reply": answer})
            return
        if path == "/api/listen":
            app.listen_async("manual")
            self._json({"ok": True})
            return
        if path == "/api/stop":
            app.speaker.stop()
            app.push_state("idle")
            self._json({"ok": True})
            return
        if path == "/api/settings":
            self._json({"settings": app.update_settings(body)})
            return
        if path == "/api/test_voice":
            app.speaker.say(str(body.get("text") or "Hi, I'm Helpie. This is how I sound."))
            self._json({"ok": True})
            return
        if path == "/api/notes/clear":
            actions.clear_notes()
            self._json({"ok": True})
            return
        if path == "/api/new_chat":
            app.brain.llm.reset()
            app.brain.pending = None
            self._json({"ok": True})
            return
        if path == "/api/update/apply":
            result = updater.apply(str(body.get("url", "")))
            self._json(result)
            return
        if path == "/api/quit":
            self._json({"ok": True})
            threading.Timer(0.2, app.shutdown).start()
            return
        self._json({"error": "unknown endpoint"}, 404)


# --------------------------------------------------------------------------- #
#  Boot
# --------------------------------------------------------------------------- #
def free_port(preferred: int = 8765) -> int:
    for port in [preferred] + list(range(8766, 8800)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(app: App, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    app.server = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
