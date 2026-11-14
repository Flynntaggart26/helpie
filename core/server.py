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
import autostart
import config
import history
import memory
import plugins
import reminders
import routines
import updater
from brain import Brain
from voice import Listener, Speaker, WakeWordListener, list_microphones

ROOT = config.APP_DIR
UI_DIR = ROOT / "ui"
TINY_W, TINY_H = 360, 180

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

    def last_id(self) -> int:
        with self._lock:
            return self._items[-1]["id"] if self._items else 0


# --------------------------------------------------------------------------- #
#  Tiny window helper
# --------------------------------------------------------------------------- #
def open_tiny_window(port: int) -> None:
    """Launch a small Edge app window near the cursor for wake-word interactions."""
    try:
        import ctypes
        from pathlib import Path
        import subprocess

        EDGE_PATHS = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        CHROME_PATHS = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]

        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
        width = int(user32.GetSystemMetrics(0))
        height = int(user32.GetSystemMetrics(1))

        # Get cursor position
        pt = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        cursor_x, cursor_y = pt.x, pt.y

        x = min(cursor_x + 20, width - TINY_W - 20)
        y = min(cursor_y + 20, height - TINY_H - 20)

        profile = config.DATA_DIR / "browser"
        profile.mkdir(parents=True, exist_ok=True)

        executable = next((p for p in EDGE_PATHS if Path(p).exists()), None)
        if executable is None:
            executable = next((p for p in CHROME_PATHS if Path(p).exists()), None)

        url = f"http://127.0.0.1:{port}/?view=tiny"
        if executable:
            subprocess.Popen([
                executable,
                f"--app={url}",
                f"--window-size={TINY_W},{TINY_H}",
                f"--window-position={x},{y}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--no-service-autorun",
                "--disable-notifications",
                "--disable-features=msEdgeSyncPromo,msEdgeSplitScreen,msEdgeSidebar",
            ])
        else:
            import webbrowser
            webbrowser.open(url)
    except Exception as e:
        print(f"[TinyWindow] Failed to open: {e}")


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
        self.wake_word = WakeWordListener(on_wake=self._on_wake_word)
        self.brain = Brain(self.cfg, on_speak=self._speak, on_quit=self.shutdown,
                           on_event=self.bus.push)
        self.brain._app = self  # Give brain access to app for plugin commands
        self.history = history.History()
        self.reminders = reminders.store
        self.reminders.on_fire = self._on_reminder
        self.reminders.start()
        actions.set_background_mode(bool(self.cfg.get("background_apps", True)))
        
        # Initialize plugin manager
        self.plugins = plugins.manager
        self.plugins.set_core_api(self)
        self.plugins.load_all()
        
        self._start_wake_word()

    def _start_wake_word(self) -> None:
        if self.cfg.get("wake_word", True):
            access_key = self.cfg.get("wake_word_access_key", "")
            mic_index = self.cfg.get("mic_index")
            ok = self.wake_word.start(access_key=access_key, mic_index=mic_index)
            if not ok:
                print("[WakeWord] Could not start (pvporcupine not installed or no access key)")

    def _on_wake_word(self) -> None:
        """Called when wake word is detected."""
        if self._closing or self._listen_lock.locked():
            return
        print("[WakeWord] Triggered -> opening tiny window, capturing screen, starting listen")

        # Open tiny window near cursor
        try:
            open_tiny_window(self.port if hasattr(self, 'port') else 8765)
        except Exception as e:
            print(f"[WakeWord] Failed to open tiny window: {e}")

        # Capture screen and analyze in background
        threading.Thread(target=self._wake_word_screen_analysis, daemon=True).start()

        # Start listening
        self.listen_async("wake_word")

    def _wake_word_screen_analysis(self) -> None:
        """Capture screen and get AI analysis after wake word."""
        try:
            if not self.brain.llm.available:
                return
            if getattr(self.brain.llm, "provider", "gemini") != "gemini":
                return

            image = actions.capture_screen()
            if not image:
                return

            answer = self.brain.llm.vision("What is on the user's screen right now? Describe briefly.", image)
            if answer:
                # Push to UI as a system message
                self.bus.push({"type": "message", "role": "assistant", "text": f"👁️ {answer}"})
                self.history.append("assistant", f"👁️ {answer}")
                self.speaker.say(f"I see: {answer}")
        except Exception as e:
            print(f"[WakeWord] Screen analysis failed: {e}")

    def _stop_wake_word(self) -> None:
        try:
            self.wake_word.stop()
        except Exception:
            pass

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
        self.history.append("user", user_text)
        self.push_state("thinking")
        try:
            answer = self.brain.handle(user_text)
        except Exception:
            traceback.print_exc()
            answer = "Something went wrong on my side, but I'm still here."
        self.bus.push({"type": "message", "role": "assistant", "text": answer})
        self.history.append("assistant", answer)
        self.bus.push({"type": "history", "chats": self.history.list_chats()})
        self.speaker.say(answer)
        return answer

    def _on_reminder(self, item: dict) -> None:
        text = str(item.get("text") or "Reminder")
        line = f"Reminder: {text}"
        self.bus.push({"type": "message", "role": "assistant", "text": line})
        self.history.append("assistant", line)
        self.bus.push({"type": "reminders", "reminders": self.reminders.list()})
        self.speaker.say(line)

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
        safe = {k: v for k, v in self.cfg.items() if k not in ("api_key", "openai_key")}
        safe["has_key"] = bool(self.cfg.get("api_key"))
        safe["key_hint"] = ("•" * 6 + self.cfg["api_key"][-4:]) if self.cfg.get("api_key") else ""
        # Ollama settings
        safe["ollama_url"] = self.cfg.get("ollama_url", "http://localhost:11434")
        safe["ollama_model"] = self.cfg.get("ollama_model", "llama3.2")
        # OpenAI-compatible settings
        safe["openai_url"] = self.cfg.get("openai_url", "")
        safe["openai_model"] = self.cfg.get("openai_model", "")
        # OpenAI key hint
        openai_key = self.cfg.get("openai_key", "")
        safe["openai_key_hint"] = ("•" * 6 + openai_key[-4:]) if openai_key else ""
        safe["has_openai_key"] = bool(openai_key)
        try:
            safe["autostart"] = autostart.enabled()
        except Exception:
            safe["autostart"] = False
        return safe

    def update_settings(self, patch: dict) -> dict:
        allowed = {"user_name", "provider", "api_key", "model", "voice", "rate", "volume",
                   "mic_index", "language", "auto_listen", "continuous", "auto_turns",
                   "city", "check_updates", "background_apps", "wake_word", "wake_word_access_key",
                   "ollama_url", "ollama_model", "openai_url", "openai_key", "openai_model"}
        for key, value in (patch or {}).items():
            if key in allowed:
                self.cfg[key] = value
        if isinstance(patch, dict) and "autostart" in patch:
            autostart.set_enabled(bool(patch.get("autostart")))
        config.save(self.cfg)
        actions.set_background_mode(bool(self.cfg.get("background_apps", True)))
        # Restart wake word if settings changed
        if "wake_word" in patch or "wake_word_access_key" in patch or "mic_index" in patch:
            self._stop_wake_word()
            self._start_wake_word()
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
        self._stop_wake_word()
        try:
            self.plugins.shutdown()
        except Exception:
            pass
        try:
            import keyboard

            keyboard.unhook_all()
        except Exception:
            pass
        try:
            import wintools

            wintools.close_browser_window()
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
                current = app.history.current_chat()
                self._json({
                    "settings": app.public_cfg(),
                    "mics": list_microphones(),
                    "voices": VOICES,
                    "languages": LANGUAGES,
                    "version": updater.current_version(),
                    "state": app.state,
                    "chats": app.history.list_chats(),
                    "current_chat": current["id"],
                    "chat": current,
                    "reminders": app.reminders.list(),
                    "memory": memory.list_items(),
                    "plugins": app.plugins.list_plugins(),
                    "last_event": app.bus.last_id(),
                })
                return
            if path == "/api/history":
                chat_id = (query.get("chat", [""])[0] or "").strip()
                if chat_id:
                    chat = app.history.get(chat_id)
                    if not chat:
                        self._json({"error": "chat not found"}, 404)
                        return
                    self._json({"chat": chat})
                    return
                self._json({"chats": app.history.list_chats()})
                return
            if path == "/api/reminders":
                self._json({"reminders": app.reminders.list()})
                return
            if path == "/api/memory":
                self._json({"memory": memory.list_items()})
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
            if path == "/api/plugins":
                self._json({"plugins": app.plugins.list_plugins()})
                return
            if path == "/api/plugins/discover":
                self._json({"plugins": app.plugins.discover()})
                return
            if path == "/api/routines":
                self._json({"routines": routines.list_routines()})
                return
            if path == "/api/routines/templates":
                self._json({"templates": routines.list_templates()})
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
            chat = app.history.new_chat()
            app.bus.push({"type": "history", "chats": app.history.list_chats()})
            self._json({"ok": True, "chat": chat})
            return
        if path == "/api/history/select":
            chat = app.history.select(str(body.get("id", "")))
            if not chat:
                self._json({"error": "chat not found"}, 404)
                return
            app.brain.llm.reset()
            app.brain.pending = None
            app.bus.push({"type": "history", "chats": app.history.list_chats()})
            self._json({"ok": True, "chat": chat})
            return
        if path == "/api/history/delete":
            removed = app.history.delete(str(body.get("id", "")))
            app.bus.push({"type": "history", "chats": app.history.list_chats()})
            self._json({"ok": removed})
            return
        if path == "/api/reminders/delete":
            removed = app.reminders.remove(str(body.get("id", "")))
            app.bus.push({"type": "reminders", "reminders": app.reminders.list()})
            self._json({"ok": removed})
            return
        if path == "/api/reminders/clear":
            app.reminders.clear()
            app.bus.push({"type": "reminders", "reminders": app.reminders.list()})
            self._json({"ok": True, "reminders": []})
            return
        if path == "/api/reminders":
            text = str(body.get("text", "")).strip()
            minutes = float(body.get("minutes", 0) or 0)
            if not text or minutes <= 0:
                self._json({"error": "text and minutes are required"}, 400)
                return
            item = app.reminders.add_in(minutes * 60, text)
            app.bus.push({"type": "reminders", "reminders": app.reminders.list()})
            self._json({"ok": True, "reminder": item})
            return
        if path == "/api/memory":
            text = str(body.get("text", "")).strip()
            item = memory.add(text)
            if not item:
                self._json({"error": "text is required"}, 400)
                return
            app.brain.llm.memory_text = memory.as_prompt()
            app.bus.push({"type": "memory", "items": memory.list_items()})
            self._json({"ok": True, "item": item, "memory": memory.list_items()})
            return
        if path == "/api/memory/delete":
            removed = memory.remove(str(body.get("text", "")))
            app.brain.llm.memory_text = memory.as_prompt()
            app.bus.push({"type": "memory", "items": memory.list_items()})
            self._json({"ok": removed, "memory": memory.list_items()})
            return
        if path == "/api/memory/clear":
            memory.clear()
            app.brain.llm.memory_text = memory.as_prompt()
            app.bus.push({"type": "memory", "items": []})
            self._json({"ok": True, "memory": []})
            return

        # --- Plugins ---
        if path == "/api/plugins":
            self._json({"plugins": app.plugins.list_plugins()})
            return
        if path == "/api/plugins/discover":
            self._json({"plugins": app.plugins.discover()})
            return
        if path == "/api/plugins/load":
            name = str(body.get("name", "")).strip()
            if not name:
                self._json({"error": "name required"}, 400)
                return
            ok = app.plugins.enable(name)
            self._json({"ok": ok, "plugins": app.plugins.list_plugins()})
            return
        if path == "/api/plugins/unload":
            name = str(body.get("name", "")).strip()
            if not name:
                self._json({"error": "name required"}, 400)
                return
            ok = app.plugins.disable(name)
            self._json({"ok": ok, "plugins": app.plugins.list_plugins()})
            return
        if path == "/api/plugins/reload":
            name = str(body.get("name", "")).strip()
            if not name:
                self._json({"error": "name required"}, 400)
                return
            ok = app.plugins.reload(name)
            self._json({"ok": ok, "plugins": app.plugins.list_plugins()})
            return
        if path == "/api/plugins/settings":
            name = str(body.get("name", "")).strip()
            if not name:
                self._json({"error": "name required"}, 400)
                return
            plugin = app.plugins.get(name)
            if not plugin:
                self._json({"error": "plugin not found"}, 404)
                return
            if body.get("get"):
                self._json({"settings": plugin.settings, "schema": plugin.manifest.settings_schema})
            else:
                key = str(body.get("key", "")).strip()
                value = body.get("value")
                if key:
                    plugin.settings[key] = value
                    # Save to file
                    settings_file = plugin.manifest.path.parent / "settings.json"
                    try:
                        settings_file.write_text(json.dumps(plugin.settings, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                    self._json({"ok": True, "settings": plugin.settings})
                else:
                    self._json({"error": "key required"}, 400)
            return

        # --- Routines ---
        if path == "/api/routines":
            self._json({"routines": routines.list_routines()})
            return
        if path == "/api/routines/templates":
            self._json({"templates": routines.list_templates()})
            return
        if path == "/api/routines/save":
            name = str(body.get("name", "")).strip()
            steps = body.get("steps", [])
            description = str(body.get("description", ""))
            if not name:
                self._json({"error": "name required"}, 400)
                return
            if not steps:
                self._json({"error": "steps required"}, 400)
                return
            ok = routines.save_routine(name, steps, description)
            self._json({"ok": ok})
            return
        if path == "/api/routines/delete":
            name = str(body.get("name", "")).strip()
            if not name:
                self._json({"error": "name required"}, 400)
                return
            ok = routines.delete_routine(name)
            self._json({"ok": ok})
            return
        if path == "/api/routines/run":
            name = str(body.get("name", "")).strip()
            params = body.get("params", {}) or {}
            if not name:
                self._json({"error": "name required"}, 400)
                return
            # Run in background to avoid blocking
            threading.Thread(target=lambda: app.brain._run_routine(name, params), daemon=True).start()
            self._json({"ok": True, "message": f"Running routine '{name}'..."})
            return
        if path == "/api/routines/template":
            name = str(body.get("name", "")).strip()
            template = str(body.get("template", "")).strip()
            if not name or not template:
                self._json({"error": "name and template required"}, 400)
                return
            ok = routines.create_routine_from_template(name, template)
            self._json({"ok": ok})
            return

        if path == "/api/mic/test":
            try:
                seconds = float(body.get("seconds", 4) or 4)
            except (TypeError, ValueError):
                seconds = 4.0
            app.bus.push({"type": "mictest", "value": "start"})
            last_push = [0.0]

            def on_level(value: float) -> None:
                now = time.time()
                if now - last_push[0] > 0.07:
                    last_push[0] = now
                    app.bus.push({"type": "miclevel", "value": round(value, 3)})

            result = app.listener.probe(app.cfg.get("mic_index"), seconds, on_level)
            app.bus.push({"type": "micresult", **result})
            self._json(result)
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
