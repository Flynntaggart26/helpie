"""Local web server + JSON API for the Helpie UI."""
from __future__ import annotations

import itertools
import base64
import ctypes
import hmac
import json
import mimetypes
import os
import socket
import threading
import time
import traceback
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import actions
import audit
import autostart
import config
import file_review
import history
import memory
import plugins
import reminders
import recycle_broker
import routines
import updater
import visual_notes
import windows_file_identity
from brain import Brain, VISUAL_SCHEMA_VERSION
from voice import Listener, Speaker, WakeWordListener, list_microphones

ROOT = config.APP_DIR
UI_DIR = ROOT / "ui"
MAX_REQUEST_BODY = 1_048_576


VOICES = [
    {"id": "en-US-AriaNeural", "label": "Aria — English (US, female)"},
    {"id": "en-US-GuyNeural", "label": "Guy — English (US, male)"},
    {"id": "en-US-JennyNeural", "label": "Jenny — English (US, female)"},
    {"id": "en-US-AvaMultilingualNeural", "label": "Ava — multilingual (female)"},
    {"id": "en-US-EmmaMultilingualNeural", "label": "Emma — multilingual (female)"},
    {"id": "en-US-AndrewMultilingualNeural", "label": "Andrew — multilingual (male)"},
    {"id": "en-US-BrianMultilingualNeural", "label": "Brian — multilingual (male)"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia — English (UK)"},
    {"id": "en-GB-RyanNeural", "label": "Ryan — English (UK)"},
    {"id": "en-GB-LibbyNeural", "label": "Libby — English (UK)"},
    {"id": "tr-TR-EmelNeural", "label": "Emel — Turkish"},
    {"id": "tr-TR-AhmetNeural", "label": "Ahmet — Turkish"},
]

LANGUAGES = [
    {"id": "groq-auto", "label": "Turkish + English (Groq multilingual)"},
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
# --------------------------------------------------------------------------- #
#  Application
# --------------------------------------------------------------------------- #
class App:
    def __init__(self) -> None:
        self.cfg = config.load()
        if self.cfg.get("screen_capture_target") not in {"picker", "region"}:
            # Older monitor/window choices are replaced with the native
            # per-request picker, which requires a fresh user selection.
            self.cfg["screen_capture_target"] = "picker"
            self.cfg["screen_capture_target_id"] = ""
        self._no_voice = os.environ.get("HELPIE_NO_VOICE") == "1"
        self.api_token = os.urandom(32).hex()
        self.bus = EventBus()
        self.state = "idle"
        self._listen_lock = threading.Lock()
        self._voice_turn_guard = threading.Lock()
        self._voice_cancel: Optional[threading.Event] = None
        self._turns_lock = threading.Lock()
        self._active_turns: set[threading.Event] = set()
        self._push_to_talk_stop = threading.Event()
        self._push_to_talk_stop.set()
        self._push_to_talk_guard = threading.Lock()
        self._pointer_state_lock = threading.Lock()
        self._pointer_left_down = False
        self._pointer_click_id = 0
        self._listening = False
        self._voice_level = 0.0
        self.file_review_drafts = file_review.ReviewDrafts(
            native_reader=windows_file_identity.read_guarded_identity if os.name == "nt" else None)
        self.recycle_broker = recycle_broker.RecycleBroker(verify=lambda _candidate: False)
        self._speech_level: Optional[float] = None
        self._speech_error = ""
        self._speech_error_until = 0.0
        self._closing = False
        self._speaking = False
        self._cloud_voice_active = False
        self._screen_frame_transfer = {"active": False, "remote": False}
        self._live_capture_lock = threading.Lock()
        self._live_capture_last_check = 0.0
        self._live_capture_last_stop = 0.0
        self._live_capture_status = {"state": "off", "active": False, "frame_ready": False,
                                     "target": "", "captured_at_ms": ""}
        self._visual_annotations_lock = threading.Lock()
        self._visual_turn = threading.local()
        self._visual_annotations = {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "revision": 0, "items": [], "expires_at": 0.0,
        }
        self._latest_visual_answer = {"items": [], "expires_at": 0.0}
        self._turn = 0
        self.server: Optional[ThreadingHTTPServer] = None

        self.speaker = Speaker(
            voice=self.cfg["voice"],
            rate=self.cfg["rate"],
            volume=self.cfg["volume"],
            cloud_consent=bool(self.cfg.get("cloud_tts_consent", False)),
            on_start=self._on_speak_start,
            on_end=self._on_speak_end,
            on_error=self._on_speak_error,
            on_level=self._on_speak_level,
        )
        self.listener = Listener()
        self.wake_word = WakeWordListener(on_wake=self._on_wake_word)
        self.brain = Brain(self.cfg, on_speak=self._speak, on_quit=self.shutdown,
                           on_event=self._on_brain_event)
        self.brain._app = self  # Give brain access to app for plugin commands
        self.history = history.History()
        self.reminders = reminders.store
        self.reminders.on_fire = self._on_reminder
        self.reminders.start()
        actions.set_background_mode(bool(self.cfg.get("background_apps", True)))
        actions.set_screen_context_consent(bool(self.cfg.get("screen_context_consent", False)))
        actions.set_screen_capture_target(
            str(self.cfg.get("screen_capture_target", "picker")),
            str(self.cfg.get("screen_capture_target_id", "")),
            self.cfg.get("screen_capture_region"),
        )
        # Initialize plugin manager
        self.plugins = plugins.manager
        self.plugins.set_core_api(self)
        self.plugins.load_all()

        self._start_wake_word()

    def pointer_position(self) -> Optional[dict]:
        """Return the current cursor position, sampled locally for the overlay."""
        if os.name != "nt":
            return None
        try:
            point = wintypes.POINT()
            if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                return None
            button_state = int(ctypes.windll.user32.GetAsyncKeyState(0x01))
        except (AttributeError, OSError):
            return None

        left_down = bool(button_state & 0x8000)
        pressed_since_sample = bool(button_state & 0x0001)
        with self._pointer_state_lock:
            if (left_down and not self._pointer_left_down) or pressed_since_sample:
                self._pointer_click_id += 1
            self._pointer_left_down = left_down
            click_id = self._pointer_click_id

        return {"x": int(point.x), "y": int(point.y), "click_id": click_id}

    def overlay_capture_status(self) -> dict:
        """Keep a consented local frame session aligned with the visible companion."""
        if not (self.cfg.get("screen_context_consent", False)
                and self.cfg.get("companion_live_view_consent", False)):
            with self._live_capture_lock:
                was_active = bool(self._live_capture_status.get("active"))
                now = time.monotonic()
                if was_active or now - self._live_capture_last_stop >= 1.0:
                    try:
                        import shell
                        shell.stop_live_capture()
                    except Exception:
                        pass
                    self._live_capture_last_stop = now
                if was_active:
                    audit.log("Stopped local companion screen capture", source="screen")
                self._live_capture_status = {
                    "state": "off", "active": False, "frame_ready": False,
                    "target": "", "captured_at_ms": "",
                }
                return dict(self._live_capture_status)

        now = time.monotonic()
        if now - self._live_capture_last_check >= 1.0:
            with self._live_capture_lock:
                now = time.monotonic()
                if now - self._live_capture_last_check >= 1.0:
                    self._live_capture_last_check = now
                    try:
                        import shell
                        current = shell.live_capture_status()
                        if (current is not None and current.get("companion_active")
                                and not current.get("active")):
                            shell.start_live_capture()
                            current = shell.live_capture_status()
                        if current is None:
                            self._live_capture_status = {
                                "state": "unavailable", "active": False,
                                "frame_ready": False, "target": "",
                                "captured_at_ms": "",
                            }
                        else:
                            was_active = bool(self._live_capture_status.get("active"))
                            active = bool(current.get("active"))
                            ready = active and bool(current.get("frame_ready"))
                            self._live_capture_status = {
                                "state": "active" if active else
                                         "unavailable" if current.get("companion_active") else "off",
                                "active": active,
                                "frame_ready": ready,
                                "target": str(current.get("target") or "Primary display"),
                                "captured_at_ms": str(current.get("captured_at_ms") or ""),
                            }
                            if active and not was_active:
                                audit.log("Started local companion screen capture",
                                          self._live_capture_status["target"], source="screen")
                            elif was_active and not active:
                                audit.log("Stopped local companion screen capture", source="screen")
                    except Exception:
                        self._live_capture_status = {
                            "state": "unavailable", "active": False,
                            "frame_ready": False, "target": "",
                            "captured_at_ms": "",
                        }
        return dict(self._live_capture_status)

    def set_visual_annotations(self, items: list[dict], duration_ms: int) -> None:
        duration_ms = max(1000, min(15000, int(duration_ms)))
        with self._visual_annotations_lock:
            revision = int(self._visual_annotations.get("revision", 0)) + 1
            self._visual_annotations = {
                "schema_version": VISUAL_SCHEMA_VERSION,
                "revision": revision,
                "items": items,
                "duration_ms": duration_ms,
                "expires_at": time.monotonic() + duration_ms / 1000,
            }
            if items:
                self._latest_visual_answer = {
                    "items": items,
                    "expires_at": time.monotonic() + 600,
                }

    def latest_visual_answer(self) -> list[dict]:
        with self._visual_annotations_lock:
            current = self._latest_visual_answer
            if current.get("expires_at", 0.0) <= time.monotonic():
                self._latest_visual_answer = {"items": [], "expires_at": 0.0}
                return []
            return list(current.get("items", []))

    def clear_visual_annotations(self) -> None:
        with self._visual_annotations_lock:
            revision = int(self._visual_annotations.get("revision", 0)) + 1
            self._visual_annotations = {
                "schema_version": VISUAL_SCHEMA_VERSION, "revision": revision,
                "items": [], "expires_at": 0.0,
            }

    def current_visual_annotations(self) -> dict:
        with self._visual_annotations_lock:
            current = self._visual_annotations
            if current.get("items") and current.get("expires_at", 0.0) <= time.monotonic():
                revision = int(current.get("revision", 0)) + 1
                self._visual_annotations = {
                    "schema_version": VISUAL_SCHEMA_VERSION, "revision": revision,
                    "items": [], "expires_at": 0.0,
                }
                current = self._visual_annotations
            return {
                "schema_version": int(current.get("schema_version", 0)),
                "revision": int(current.get("revision", 0)),
                "items": list(current.get("items", [])),
                "duration_ms": int(current.get("duration_ms", 0)),
                "active_index": current.get("active_index"),
            }

    # -- events ---------------------------------------------------------- #
    def push(self, event: dict) -> None:
        self.bus.push(event)

    def push_state(self, state: str, detail: str = "") -> None:
        self.state = state
        self.bus.push({"type": "state", "value": state, "detail": detail})

    def _on_brain_event(self, event: dict) -> None:
        if event.get("type") == "state":
            self.state = str(event.get("value") or "idle")
        if event.get("type") == "screen_frame_transfer":
            self._screen_frame_transfer = {
                "active": bool(event.get("active")),
                "remote": bool(event.get("remote")),
            }
        if event.get("type") == "visual_annotations":
            items = event.get("items")
            if isinstance(items, list):
                clean = [{k: v for k, v in item.items() if k != "explanation"} for item in items]
                self._visual_turn.links = [(item.get("explanation", ""), index)
                                           for index, item in enumerate(items) if item.get("explanation")]
                self.set_visual_annotations(clean, event.get("duration_ms", 12000))
        self.bus.push(event)

    def _start_wake_word(self) -> None:
        if self._no_voice or not self.cfg.get("wake_word", False):
            return
        access_key = self.cfg.get("wake_word_access_key", "")
        mic_index = self.cfg.get("mic_index")
        ok = self.wake_word.start(access_key=access_key, mic_index=mic_index)
        if not ok:
            print("[WakeWord] Could not start (pvporcupine not installed or no access key)")

    def _on_wake_word(self) -> None:
        """Called when wake word is detected."""
        if self._closing or self._listen_lock.locked():
            return
        print("[WakeWord] Triggered -> opening tiny window and starting listen")

        # Open tiny window near cursor via shell control endpoint.
        try:
            import shell
            shell.request("companion")
        except Exception as e:
            print(f"[WakeWord] Failed to open tiny window: {e}")

        # Start listening
        self.listen_async("wake_word")

    def _stop_wake_word(self) -> None:
        try:
            self.wake_word.stop()
        except Exception:
            pass

    def _on_speak_start(self) -> None:
        self._speaking = True
        self._cloud_voice_active = bool(self.speaker.cloud_consent)
        self.push_state("speaking")
        self.bus.push({"type": "cloud_voice", "active": self._cloud_voice_active,
                       "mode": "speak" if self._cloud_voice_active else "speak-local"})

    def _on_speak_end(self) -> None:
        self._speaking = False
        self._speech_level = None
        self._cloud_voice_active = False
        self.bus.push({"type": "cloud_voice", "active": False})
        if not self._listening:
            self.push_state("idle")

    def _on_speak_error(self, message: str) -> None:
        self._speech_error = message
        self._speech_error_until = time.monotonic() + 15.0
        self.bus.push({"type": "error", "kind": "speech", "text": message})

    def _on_speak_level(self, level: Optional[float]) -> None:
        self._speech_level = level

    def _speak(self, text: str) -> None:
        self.speaker.say(text)

    # -- conversation ---------------------------------------------------- #
    def reply(self, user_text: str, source: str = "chat",
              cancel_event: Optional[threading.Event] = None) -> str:
        cancel_event = cancel_event if cancel_event is not None else threading.Event()
        with self._turns_lock:
            if cancel_event.is_set():
                return ""
            self._active_turns.add(cancel_event)
        try:
            return self._reply_turn(user_text, source, cancel_event)
        finally:
            with self._turns_lock:
                self._active_turns.discard(cancel_event)

    def _reply_turn(self, user_text: str, source: str, cancel_event: threading.Event) -> str:
        if cancel_event and cancel_event.is_set():
            return ""
        self._visual_turn.links = []
        self.bus.push({"type": "message", "role": "user", "text": user_text})
        self.history.append("user", user_text)
        self.push_state("thinking")
        try:
            answer = self.brain.handle(
                user_text,
                allow_screen_capture=source in {"chat", "companion"},
                source=source,
                cancel_event=cancel_event,
            )
        except Exception:
            traceback.print_exc()
            answer = "Something went wrong on my side, but I'm still here."
        if cancel_event and cancel_event.is_set():
            return ""
        self.bus.push({"type": "message", "role": "assistant", "text": answer})
        self.history.append("assistant", answer)
        self.bus.push({"type": "history", "chats": self.history.list_chats()})
        links = list(self._visual_turn.links)
        with self._visual_annotations_lock:
            visual_items = self._visual_annotations.get("items")
        def highlight_piece(piece: str) -> None:
            matches = [index for phrase, index in links if phrase in piece]
            with self._visual_annotations_lock:
                current = self._visual_annotations
                if current.get("items") is visual_items and current.get("expires_at", 0) > time.monotonic():
                    active = matches[0] if matches else None
                    if current.get("active_index") != active:
                        current["active_index"] = active
                        current["revision"] += 1
        if cancel_event:
            with self._voice_turn_guard:
                if not cancel_event.is_set():
                    self.speaker.say(answer, on_piece=highlight_piece if links else None)
        else:
            self.speaker.say(answer, on_piece=highlight_piece if links else None)
        return answer

    def _on_reminder(self, item: dict) -> None:
        text = str(item.get("text") or "Reminder")
        line = f"Reminder: {text}"
        self.bus.push({"type": "message", "role": "assistant", "text": line})
        self.history.append("assistant", line)
        self.bus.push({"type": "reminders", "reminders": self.reminders.list()})
        self.speaker.say(line)

    def listen(self, reason: str = "manual", cancel_event: Optional[threading.Event] = None) -> None:
        push_to_talk = reason == "push_to_talk"
        if cancel_event and cancel_event.is_set():
            return
        if self._no_voice:
            if push_to_talk:
                self._push_to_talk_stop.set()
            self.push_state("idle")
            self.bus.push({"type": "error", "text": "Voice input is disabled in this run."})
            return
        multilingual = self.cfg.get("language") == "groq-auto"
        consent = "groq_speech_consent" if multilingual else "cloud_speech_consent"
        if not self.cfg.get(consent, False) or (multilingual and not self.cfg.get("groq_speech_key")):
            if push_to_talk:
                self._push_to_talk_stop.set()
            self.push_state("idle")
            self.bus.push({
                "type": "error",
                "text": ("Enable Groq transcription and save a Groq speech key in Settings → Voice."
                         if multilingual else "Enable Google transcription in Settings → Voice. Typed commands still work."),
            })
            return
        if not self._listen_lock.acquire(blocking=False):
            if push_to_talk:
                self._push_to_talk_stop.set()
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
                    self._voice_level = max(0.0, min(1.0, value))
                    loudest = max(loudest, value)
                    now = time.time()
                    if now - last_push > 0.08:
                        last_push = now
                        self.bus.push({"type": "level", "value": round(value, 3)})

                wav = self.listener.listen(
                    mic_index=self.cfg.get("mic_index"),
                    phrase_limit=60.0 if push_to_talk else 14.0,
                    stop_event=self._push_to_talk_stop if push_to_talk else None,
                    cancel_event=cancel_event,
                    on_level=on_level,
                    on_speech=lambda: self.push_state("hearing"),
                )
                if self._closing or (cancel_event and cancel_event.is_set()):
                    break

                if not wav:
                    if loudest < 0.02 and time.time() - started > 3:
                        self.bus.push({"type": "hint", "text":
                                       "No sound reached the microphone. Check that it is on and unmuted."})
                    self.push_state("idle")
                    break

                # A permission or provider change during recording cancels this transfer.
                if (self.cfg.get("language") == "groq-auto") != multilingual or not self.cfg.get(consent, False):
                    self.push_state("idle")
                    break

                self.push_state("thinking", "transcribing…")
                self._cloud_voice_active = True
                self.bus.push({"type": "cloud_voice", "active": True, "mode": "transcribe"})
                try:
                    text = (self.listener.transcribe_multilingual(wav, self.cfg.get("groq_speech_key", ""))
                            if multilingual else self.listener.transcribe(wav, self.cfg.get("language", "en-US")))
                except Exception as exc:
                    if cancel_event and cancel_event.is_set():
                        break
                    self.push_state("idle")
                    self._cloud_voice_active = False
                    self.bus.push({"type": "cloud_voice", "active": False})
                    self.bus.push({"type": "error",
                                   "text": ("Groq transcription failed. Check your speech API key, connection and account limits."
                                            if multilingual else
                                            f"Speech recognition failed ({type(exc).__name__}). Check your connection.")})
                    break

                if cancel_event and cancel_event.is_set():
                    break

                if not text:
                    self.push_state("idle")
                    self._cloud_voice_active = False
                    self.bus.push({"type": "cloud_voice", "active": False})
                    self.bus.push({"type": "hint", "text": "I could not make out what you said."})
                    break

                self._cloud_voice_active = False
                self.bus.push({"type": "cloud_voice", "active": False})
                self.bus.push({"type": "heard", "text": text})
                self._listening = False
                self.reply(text, source="chat" if reason == "chat" else "companion",
                           cancel_event=cancel_event)
                self.speaker.wait_idle(60)
                self._listening = True

                if push_to_talk:
                    break
                if not (self.cfg.get("continuous") and reason == "auto" and not self._no_voice):
                    break
                self._turn += 1
                if self._turn >= int(self.cfg.get("auto_turns", 3)):
                    break

            self._listening = False
            self.push_state("idle")
        finally:
            self._voice_level = 0.0
            self._listening = False
            self._cloud_voice_active = False
            self.bus.push({"type": "cloud_voice", "active": False})
            if push_to_talk:
                self._push_to_talk_stop.set()
            self._listen_lock.release()

    def listen_async(self, reason: str = "manual") -> bool:
        with self._voice_turn_guard:
            if self._voice_cancel is not None or self._listen_lock.locked():
                return False
            cancel = threading.Event()
            self._voice_cancel = cancel
        def run_turn() -> None:
            try:
                self.listen(reason, cancel)
            finally:
                with self._voice_turn_guard:
                    if self._voice_cancel is cancel:
                        self._voice_cancel = None
        threading.Thread(target=run_turn, daemon=True, name="helpie-listen").start()
        return True

    def start_push_to_talk(self) -> None:
        """Start one microphone turn that ends when Ctrl+H is released."""
        with self._push_to_talk_guard:
            if not self._push_to_talk_stop.is_set() or self._listen_lock.locked():
                return
            self._push_to_talk_stop.clear()
            audit.log("Started push-to-talk voice input", source="voice")
            if not self.listen_async("push_to_talk"):
                self._push_to_talk_stop.set()

    def stop_push_to_talk(self) -> None:
        """Stop push-to-talk capture; any captured phrase is then transcribed."""
        if not self._push_to_talk_stop.is_set():
            audit.log("Stopped push-to-talk voice input", source="voice")
        self._push_to_talk_stop.set()

    def cancel_voice(self) -> None:
        with self._voice_turn_guard:
            if self._voice_cancel is not None:
                self._voice_cancel.set()
        self.stop_push_to_talk()
        self.speaker.stop()

    def cancel_turns(self) -> None:
        with self._turns_lock:
            for cancel in self._active_turns:
                cancel.set()

    # -- settings -------------------------------------------------------- #
    def public_cfg(self) -> dict:
        safe = {k: v for k, v in self.cfg.items()
                if k not in ("api_key", "openai_key", "wake_word_access_key", "groq_speech_key")
                and k not in ("api_key_enc", "openai_key_enc", "wake_word_access_key_enc", "groq_speech_key_enc")}
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
        safe["has_groq_speech_key"] = bool(self.cfg.get("groq_speech_key"))
        safe["has_screen_context_consent"] = bool(self.cfg.get("screen_context_consent"))
        safe["has_wake_word_key"] = bool(self.cfg.get("wake_word_access_key"))
        try:
            safe["autostart"] = autostart.enabled()
        except Exception:
            safe["autostart"] = False
        # Weather for tiny-window dashboard (best effort, never blocks init)
        try:
            safe["weather"] = actions.weather(self.cfg.get("city", ""), timeout=3.0)
        except Exception:
            safe["weather"] = ""
        return safe

    def update_settings(self, patch: dict, *, broadcast: bool = True) -> dict:
        previous_cfg = dict(self.cfg)
        self.cfg = dict(self.cfg)
        allowed = {"user_name", "provider", "api_key", "model", "voice", "rate", "volume",
                   "mic_index", "language", "cloud_speech_consent", "groq_speech_consent", "groq_speech_key", "cloud_tts_consent",
                   "screen_context_consent", "companion_live_view_consent",
                   "screen_capture_target", "screen_capture_target_id",
                   "screen_capture_region",
                   "wake_word", "wake_word_access_key",
                   "auto_listen", "continuous", "auto_turns",
                   "city", "check_updates", "background_apps",
                   "theme", "ollama_url", "ollama_model", "openai_url", "openai_key", "openai_model"}
        for key, value in (patch or {}).items():
            if key in allowed:
                # Empty password inputs mean "keep the saved credential".
                if key in {"api_key", "openai_key", "wake_word_access_key", "groq_speech_key"} and not value:
                    continue
                if key == "provider" and value not in ("gemini", "ollama", "openai"):
                    continue
                if key == "language" and value not in {item["id"] for item in LANGUAGES}:
                    continue
                if key == "groq_speech_key" and (not isinstance(value, str) or len(value) > 512):
                    continue
                if key in {"screen_context_consent", "companion_live_view_consent",
                           "cloud_speech_consent", "groq_speech_consent", "cloud_tts_consent"}:
                    if not isinstance(value, bool):
                        continue
                if key == "screen_capture_target" and value not in (
                        "picker", "region"):
                    continue
                if key == "screen_capture_target_id" and (
                        not isinstance(value, str) or len(value) > 128):
                    continue
                if key == "screen_capture_region":
                    if not isinstance(value, dict):
                        continue
                    raw_values = [value.get(field) for field in ("x", "y", "width", "height")]
                    if any(isinstance(number, bool) or not isinstance(number, (int, float))
                           for number in raw_values):
                        continue
                    try:
                        x, y, width, height = (float(number) for number in raw_values)
                    except (KeyError, TypeError, ValueError):
                        continue
                    if (not all(0 <= number <= 1 for number in (x, y, width, height))
                            or width <= 0 or height <= 0 or x + width > 1 or y + height > 1):
                        continue
                self.cfg[key] = value
        # Companion capture is a narrower permission inside full-chat screen
        # consent. Never persist it enabled after the broader permission is off.
        if not self.cfg.get("screen_context_consent", False):
            self.cfg["companion_live_view_consent"] = False
        if isinstance(patch, dict) and "autostart" in patch:
            autostart.set_enabled(bool(patch.get("autostart")))
        try:
            config.save(self.cfg)
        except Exception:
            self.cfg = previous_cfg
            raise
        actions.set_background_mode(bool(self.cfg.get("background_apps", True)))
        actions.set_screen_context_consent(bool(self.cfg.get("screen_context_consent", False)))
        actions.set_screen_capture_target(
            str(self.cfg.get("screen_capture_target", "picker")),
            str(self.cfg.get("screen_capture_target_id", "")),
            self.cfg.get("screen_capture_region"),
        )
        live_view_allowed = bool(self.cfg.get("screen_context_consent", False)
                                 and self.cfg.get("companion_live_view_consent", False))
        previous_live_view_allowed = bool(previous_cfg.get("screen_context_consent", False)
                                          and previous_cfg.get("companion_live_view_consent", False))
        if ((previous_cfg.get("screen_context_consent") and not self.cfg.get("screen_context_consent"))
                or (previous_live_view_allowed and not live_view_allowed)):
            self.cancel_turns()
        if not live_view_allowed and (previous_live_view_allowed
                                      or self._live_capture_status.get("active")):
            with self._live_capture_lock:
                try:
                    import shell
                    shell.stop_live_capture()
                except Exception:
                    pass
                self._live_capture_status = {
                    "state": "off", "active": False, "frame_ready": False,
                    "target": "", "captured_at_ms": "",
                }
                self._live_capture_last_check = 0.0
            audit.log("Stopped local companion screen capture", source="screen")
        # Restart wake word if settings changed
        if "wake_word" in patch or "wake_word_access_key" in patch or "mic_index" in patch:
            self._stop_wake_word()
            self._start_wake_word()
        self.brain.refresh(self.cfg)
        self.speaker.update(self.cfg.get("voice"), self.cfg.get("rate"), self.cfg.get("volume"),
                            cloud_consent=bool(self.cfg.get("cloud_tts_consent", False)))
        if broadcast:
            self.bus.push({"type": "settings", "value": self.public_cfg()})
        return self.public_cfg()

    # -- lifecycle ------------------------------------------------------- #
    def shutdown(self) -> None:
        self._closing = True
        self.cancel_voice()
        self.recycle_broker.cancel()
        if self._live_capture_status.get("active"):
            try:
                import shell
                shell.stop_live_capture()
            except Exception:
                pass
            audit.log("Stopped local companion screen capture", source="screen")
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
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if content_type.lower().startswith("text/html"):
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; base-uri 'none'; object-src 'none'; "
                "frame-ancestors 'none'; form-action 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                "font-src 'self' data:; media-src 'self' data: blob:; connect-src 'self'",
            )
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, data: dict, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _body(self) -> dict:
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1 or self.headers.get("Transfer-Encoding"):
            raise ValueError("invalid request framing")
        raw_length = lengths[0].strip() if lengths else "0"
        if (not raw_length or len(raw_length) > 10
                or any(character < "0" or character > "9" for character in raw_length)):
            raise ValueError("invalid Content-Length")
        length = int(raw_length)
        if length > MAX_REQUEST_BODY:
            raise OverflowError("request body too large")
        if length == 0:
            return {}
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete request body")
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("invalid JSON request body") from exc
        if not isinstance(body, dict):
            raise ValueError("request body must be a JSON object")
        return body

    def _trusted_local_request(self) -> bool:
        """Reject DNS-rebinding and cross-origin requests to this loopback server."""
        port = int(self.server.server_address[1])
        expected_host = f"127.0.0.1:{port}"
        hosts = self.headers.get_all("Host", [])
        host = hosts[0].strip().lower() if len(hosts) == 1 else ""
        if host != expected_host:
            self.close_connection = True
            self._json({"error": "invalid host"}, 421)
            return False

        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1:
            self.close_connection = True
            self._json({"error": "invalid origin"}, 403)
            return False
        origin = origins[0] if origins else None
        expected_origin = f"http://{expected_host}"
        if origin and origin.strip().lower() != expected_origin:
            self.close_connection = True
            self._json({"error": "invalid origin"}, 403)
            return False
        return True

    def _authorized_api(self) -> bool:
        token = self.headers.get("X-Helpie-Token", "")
        expected = getattr(self.app, "api_token", "")
        if expected and hmac.compare_digest(token.encode("utf-8"), expected.encode("ascii")):
            return True
        self.close_connection = True
        self._json({"error": "unauthorized"}, 403)
        return False

    def _static(self, path: str) -> None:
        relative = path.lstrip("/") or "index.html"
        root = UI_DIR.resolve()
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self._json({"error": "not found"}, 404)
            return
        if not target.is_file():
            self._json({"error": "not found"}, 404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix in {".html", ".css", ".js"}:
            content_type += "; charset=utf-8"
        content = target.read_bytes()
        if target == root / "index.html":
            content = content.replace(b"__HELPIE_API_TOKEN__", self.app.api_token.encode("ascii"))
        self._send(200, content, content_type)

    # -- routes ---------------------------------------------------------- #
    def do_GET(self) -> None:
        if not self._trusted_local_request():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        app = self.app

        if path.startswith("/api/"):
            if path != "/api/health" and not self._authorized_api():
                return
            if path == "/api/recycle/history":
                audit.log("Viewed Recycle Bin activity", source="files")
                self._json({"available": app.recycle_broker.available(),
                            "items": app.recycle_broker.recent()})
                return
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
            if path == "/api/visual-notes":
                try:
                    self._json({"notes": visual_notes.list_notes()})
                except (OSError, ValueError):
                    self._json({"error": "visual notes could not be read"}, 500)
                return
            if path == "/api/visual-notes/current":
                self._json({"items": app.latest_visual_answer()})
                return
            if path.startswith("/api/visual-notes/"):
                note_id = path.rsplit("/", 1)[-1]
                try:
                    note = visual_notes.get_note(note_id)
                except (OSError, ValueError):
                    self._json({"error": "visual note could not be read"}, 500)
                    return
                if not note:
                    self._json({"error": "visual note not found"}, 404)
                    return
                self._json({"note": note})
                return
            if path == "/api/update/check":
                self._json(updater.check())
                return
            if path == "/api/health":
                self._json({"ok": True, "version": updater.current_version()})
                return
            if path == "/api/overlay/state":
                self._json({"state": app.state,
                            "speech_error": app._speech_error if time.monotonic() < app._speech_error_until else "",
                            "voice_level": app._voice_level if app.state in {"listening", "hearing"} else 0.0,
                            "speech_level": app._speech_level if app.state == "speaking" else None,
                            "cloud_voice_active": app._cloud_voice_active,
                            "screen_frame_transfer": dict(app._screen_frame_transfer),
                            "capture_session": app.overlay_capture_status(),
                            "screen_access_enabled": bool(
                                app.cfg.get("screen_context_consent", False)
                                and app.cfg.get("companion_live_view_consent", False)
                            ),
                            "pointer_echo": app.pointer_position(),
                            "visual_annotations": app.current_visual_annotations()})
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
            if path == "/api/audit":
                try:
                    limit = int(query.get("limit", ["200"])[0])
                except (TypeError, ValueError):
                    limit = 200
                source = (query.get("source", [""])[0] or "").strip()
                self._json({"entries": audit.tail(limit, source), "stats": audit.stats()})
                return
            if path == "/api/weather":
                city = str(app.cfg.get("city", "")).strip()
                try:
                    weather_text = actions.weather(city)
                    self._json({"city": city or "auto", "weather": weather_text})
                except Exception:
                    self._json({"city": city or "auto", "weather": "Weather unavailable."})
                return
            self._json({"error": "unknown endpoint"}, 404)
            return

        self._static(path)

    def do_POST(self) -> None:
        if not self._trusted_local_request():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        if not self._authorized_api():
            return
        try:
            body = self._body()
        except OverflowError:
            self.close_connection = True
            self._json({"error": "request body too large"}, 413)
            return
        except ValueError:
            self.close_connection = True
            self._json({"error": "invalid request body"}, 400)
            return
        app = self.app

        if path in ("/api/file-review/confirm-review", "/api/file-review/cancel-review"):
            if path.endswith("/cancel-review"):
                app.file_review_drafts.cancel()
                audit.log("Cancelled read-only file review", source="files")
                self._json({"ok": True})
                return
            try:
                app.file_review_drafts.confirm(body.get("token"))
            except (OSError, ValueError):
                self._json({"error": "Review expired, changed, or could not be verified."}, 409)
                return
            audit.log("Confirmed read-only file review", source="files")
            self._json({"ok": True, "deleted": False})
            return
        if path in ("/api/file-review/preview", "/api/file-review/recheck", "/api/file-review/prepare-review"):
            roots = {"downloads": "Downloads", "desktop": "Desktop", "documents": "Documents"}
            folder = body.get("folder")
            kind = body.get("kind")
            if not isinstance(folder, str) or folder not in roots or kind not in ("files", "duplicates", "empty_folders"):
                self._json({"error": "Choose a supported folder and review type."}, 400)
                return
            try:
                root = Path.home() / roots[folder]
                if path.endswith("/preview"):
                    result = file_review.preview(root, kind)
                elif path.endswith("/recheck"):
                    result = file_review.recheck(root, kind, body.get("selected"))
                else:
                    result = {"token": app.file_review_drafts.prepare(root, kind, body.get("selected")),
                              "expires_in_seconds": file_review.DRAFT_SECONDS}
            except (OSError, ValueError):
                self._json({"error": "The selected folder could not be reviewed."}, 400)
                return
            audit.log("Reviewed files without deletion" if path.endswith("/preview")
                      else "Prepared read-only file review" if path.endswith("/prepare-review")
                      else "Rechecked files without deletion", source="files")
            self._json(result)
            return
        if path == "/api/voice/select":
            voice = body.get("voice")
            if not isinstance(voice, str) or voice not in {item["id"] for item in VOICES}:
                self._json({"error": "Choose an available voice."}, 400)
                return
            app.update_settings({"voice": voice}, broadcast=False)
            audit.log("Changed answering voice", source="settings")
            self._json({"voice": voice})
            return
        if path == "/api/voice/output":
            enabled = body.get("cloud_tts_consent")
            if not isinstance(enabled, bool):
                self._json({"error": "Choose whether to enable online speech."}, 400)
                return
            app.update_settings({"cloud_tts_consent": enabled}, broadcast=False)
            audit.log("Changed online speech setting", source="settings")
            self._json({"cloud_tts_consent": enabled})
            return
        if path == "/api/ask":
            text = str(body.get("text", "")).strip()
            source = str(body.get("source", "chat"))
            answer = app.reply(text, source="companion" if source == "companion" else "chat")
            self._json({"reply": answer})
            return
        if path == "/api/listen":
            reason = str(body.get("reason", "chat"))
            app.listen_async("companion" if reason == "companion" else "chat")
            self._json({"ok": True})
            return
        if path == "/api/listen/start":
            app.start_push_to_talk()
            self._json({"ok": True})
            return
        if path == "/api/listen/stop":
            app.stop_push_to_talk()
            self._json({"ok": True})
            return
        if path == "/api/stop":
            app.cancel_turns()
            app.cancel_voice()
            app.recycle_broker.cancel()
            app.brain.cancel_model_proposal()
            app.brain.pending = None
            app.clear_visual_annotations()
            try:
                import shell
                shell.request("hide-overlay")
                shell.stop_live_capture()
            except Exception:
                pass
            with app._live_capture_lock:
                app._live_capture_status = {"state": "off", "active": False, "frame_ready": False,
                                            "target": "", "captured_at_ms": ""}
            app.push_state("idle")
            self._json({"ok": True})
            return
        if path == "/api/overlay/annotations/clear":
            app.clear_visual_annotations()
            self._json({"ok": True})
            return
        if path == "/api/screen/preview":
            if not app.cfg.get("screen_context_consent", False):
                self._json({"error": "screen access is off"}, 403)
                return
            monitor_id = body.get("monitor_id", "")
            if not isinstance(monitor_id, str) or len(monitor_id) > 128:
                self._json({"error": "invalid capture target"}, 400)
                return
            previous_state = app.state
            preview_cancel = threading.Event()
            with app._turns_lock:
                app._active_turns.add(preview_cancel)
            app.push_state("capturing")
            try:
                preview = actions.capture_screen_preview(monitor_id)
            finally:
                with app._turns_lock:
                    app._active_turns.discard(preview_cancel)
                if not preview_cancel.is_set():
                    app.push_state(previous_state if previous_state != "capturing" else "idle")
            if preview_cancel.is_set() or not app.cfg.get("screen_context_consent", False) or not preview:
                self._json({"error": "capture was canceled or unavailable"}, 409)
                return
            try:
                audit.log("Previewed a Windows capture selection", monitor_id or "system picker",
                          source="screen")
            except Exception:
                pass
            self._json({"image": base64.b64encode(preview).decode("ascii")})
            return
        if path == "/api/overlay/hide":
            import shell

            app.cancel_turns()
            app.cancel_voice()
            app.recycle_broker.cancel()
            app.brain.cancel_model_proposal()
            app.brain.pending = None
            app.clear_visual_annotations()
            ok = shell.request("hide-overlay")
            if app._live_capture_status.get("active"):
                audit.log("Stopped local companion screen capture", source="screen")
                app._live_capture_status = {
                    "state": "off", "active": False, "frame_ready": False,
                    "target": "", "captured_at_ms": "",
                }
            self._json({"ok": ok})
            return
        if path == "/api/settings":
            try:
                settings = app.update_settings(body)
            except RuntimeError as exc:
                self._json({"error": str(exc)}, 503)
                return
            self._json({"settings": settings})
            return
        if path == "/api/test_voice":
            app.speaker.say(str(body.get("text") or "Hi, I'm Helpie. This is how I sound."))
            self._json({"ok": True})
            return
        if path == "/api/notes/clear":
            actions.clear_notes()
            self._json({"ok": True})
            return
        if path == "/api/visual-notes/save":
            try:
                note = visual_notes.save_note(
                    str(body.get("id", "")), body.get("title", ""), body.get("strokes"),
                    body.get("visual_items"),
                )
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            except OSError:
                self._json({"error": "visual note could not be saved"}, 500)
                return
            audit.log("Saved a visual note", source="notes")
            self._json({"note": note})
            return
        if path == "/api/visual-notes/exported":
            audit.log("Exported a visual note", source="notes")
            self._json({"ok": True})
            return
        if path == "/api/visual-notes/delete":
            try:
                removed = visual_notes.delete_note(str(body.get("id", "")))
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            except OSError:
                self._json({"error": "visual note could not be deleted"}, 500)
                return
            if not removed:
                self._json({"error": "visual note not found"}, 404)
                return
            audit.log("Deleted a visual note", source="notes")
            self._json({"ok": True})
            return
        if path == "/api/new_chat":
            app.brain.cancel_model_proposal()
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
            app.brain.cancel_model_proposal()
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
                secret_keys = {key for key in plugin.manifest.settings_schema if plugins.SECRET_SETTING.search(key)}
                public_settings = {key: value for key, value in plugin.settings.items() if key not in secret_keys}
                configured = {key: bool(plugin.settings.get(key)) for key in secret_keys}
                self._json({"settings": public_settings, "configured": configured,
                            "schema": plugin.manifest.settings_schema})
            else:
                key = str(body.get("key", "")).strip()
                value = body.get("value")
                if not key or key not in plugin.manifest.settings_schema:
                    self._json({"error": "valid setting key required"}, 400)
                    return
                secret = bool(plugins.SECRET_SETTING.search(key))
                if secret and not value:
                    self._json({"ok": True, "unchanged": True})
                    return
                previous = dict(plugin.settings)
                plugin.settings[key] = value
                try:
                    plugins._save_settings(plugin)
                except RuntimeError as exc:
                    plugin.settings = previous
                    self._json({"error": str(exc)}, 503)
                    return
                self._json({"ok": True})
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
            if ok:
                audit.log("Saved routine", f"{name} · {len(steps)} steps", source="routine")
            self._json({"ok": ok})
            return
        if path == "/api/routines/delete":
            name = str(body.get("name", "")).strip()
            if not name:
                self._json({"error": "name required"}, 400)
                return
            ok = routines.delete_routine(name)
            if ok:
                audit.log("Deleted routine", name, source="routine")
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
            if ok:
                audit.log("Created routine from template", f"{name} ← {template}", source="routine")
            self._json({"ok": ok})
            return

        if path == "/api/audit/clear":
            self._json({"ok": audit.clear()})
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
        if path == "/api/window":
            target = str(body.get("target", ""))
            try:
                import shell

                if target in {"full", "tiny", "hide-tiny"}:
                    self._json({"ok": shell.request(target)})
                else:
                    self._json({"error": "unknown target"}, 400)
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)})
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
