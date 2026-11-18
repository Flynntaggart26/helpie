"""Ses: mikrofon dinleme (STT) ve konusma (TTS)."""
from __future__ import annotations

import asyncio
import math
import os
import queue
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import pyaudio

    PYAUDIO_AVAILABLE = True
except Exception:  # PortAudio missing, no audio drivers, etc.
    pyaudio = None  # type: ignore[assignment]
    PYAUDIO_AVAILABLE = False

try:
    import speech_recognition as sr

    SPEECH_RECOGNITION_AVAILABLE = True
except Exception:
    sr = None  # type: ignore[assignment]
    SPEECH_RECOGNITION_AVAILABLE = False

CHUNK = 640
RATE = 16000
WIDTH = 2


# --------------------------------------------------------------------------- #
#  Mikrofon listesi
# --------------------------------------------------------------------------- #
def list_microphones() -> list[dict]:
    """Kullanılabilir mikrofonları (index, ad) olarak döndürür."""
    out: list[dict] = []
    if not SPEECH_RECOGNITION_AVAILABLE:
        return out
    try:
        for index, name in enumerate(sr.Microphone.list_microphone_names()):
            out.append({"index": index, "name": name})
    except Exception:
        pass
    return out



# --------------------------------------------------------------------------- #
#  Uyandırma kelimesi dinleyicisi (Porcupine)
# --------------------------------------------------------------------------- #
class WakeWordListener:
    """Runs a background thread that listens for 'jarvis' / 'computer' using
    Picovoice Porcupine. Requires a free AccessKey from console.picovoice.ai.

    Silently degrades when pvporcupine is not installed or no AccessKey is
    configured, so wake word is optional and never blocks startup.
    """

    def __init__(self, on_wake: Callable[[], None]) -> None:
        self.on_wake = on_wake
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._porcupine = None
        self._pa = None
        self._stream = None
        self._enabled = False

    def start(self, access_key: str = "", mic_index: Optional[int] = None) -> bool:
        """Initialize Porcupine and start listening thread.

        Returns False (and prints a message) when pvporcupine is not installed,
        PyAudio is unavailable, or no AccessKey is configured. Callers should
        treat False as "wake word unavailable" and continue normally.
        """
        if self._enabled:
            return True
        if not access_key:
            print("[WakeWord] No AccessKey configured; wake word disabled.")
            return False
        try:
            import pvporcupine
        except Exception:
            print("[WakeWord] pvporcupine not installed. Run: pip install pvporcupine")
            return False

        # Built-in keywords available on the free tier. "jarvis" is closest
        # to "Helpie" phonetically; "computer" is an alternative.
        keywords = ["jarvis", "computer"]
        try:
            self._porcupine = pvporcupine.create(
                access_key=access_key,
                keywords=keywords,
            )
        except Exception as e:
            print(f"[WakeWord] Failed to init Porcupine: {e}")
            return False

        try:
            import pyaudio
        except Exception:
            print("[WakeWord] PyAudio not available on this machine. Voice input disabled.")
            return False

        self._pa = pyaudio.PyAudio()
        try:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self._porcupine.sample_rate,
                input=True,
                frames_per_buffer=self._porcupine.frame_length,
                input_device_index=mic_index,
            )
        except Exception as e:
            print(f"[WakeWord] Failed to open mic: {e}")
            self.stop()
            return False

        self._enabled = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="wake-word")
        self._thread.start()
        print(f"[WakeWord] Listening for: {keywords}")
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._cleanup()

    def _cleanup(self) -> None:
        try:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
        except Exception:
            pass
        try:
            if self._pa:
                self._pa.terminate()
        except Exception:
            pass
        try:
            if self._porcupine:
                self._porcupine.delete()
        except Exception:
            pass
        self._stream = None
        self._pa = None
        self._porcupine = None
        self._enabled = False

    def _run(self) -> None:
        import struct

        while not self._stop.is_set():
            try:
                data = self._stream.read(self._porcupine.frame_length, exception_on_overflow=False)
                pcm = struct.unpack_from("h" * self._porcupine.frame_length, data)
                keyword_index = self._porcupine.process(pcm)
                if keyword_index >= 0:
                    keyword = ["jarvis", "computer"][keyword_index]
                    print(f"[WakeWord] Detected: {keyword}")
                    if self.on_wake:
                        self.on_wake()
            except Exception:
                time.sleep(0.1)

    def update_mic(self, mic_index: Optional[int]) -> None:
        """Restart with new microphone index."""
        was_enabled = self._enabled
        self.stop()
        if was_enabled:
            # AccessKey should have been persisted in config; caller re-pass it.
            pass


# --------------------------------------------------------------------------- #
#  Dinleyici (kendi VAD'imiz: canlı ses seviyesi + konuşma algılama)
# --------------------------------------------------------------------------- #
class Listener:
    def __init__(self) -> None:
        self.recognizer = sr.Recognizer()
        self.recognizer.operation_timeout = 15

    # -- yardımcılar -------------------------------------------------------- #
    @staticmethod
    def _rms(data: bytes) -> float:
        if not data:
            return 0.0
        try:
            import audioop

            return float(audioop.rms(data, WIDTH))
        except Exception:
            import struct

            count = len(data) // 2
            if not count:
                return 0.0
            samples = struct.unpack(f"<{count}h", data[: count * 2])
            return math.sqrt(sum(s * s for s in samples) / count)

    def _open(self, mic_index: Optional[int], rate: int) -> tuple[pyaudio.PyAudio, pyaudio.Stream]:
        if not PYAUDIO_AVAILABLE:
            raise RuntimeError("PyAudio is not available on this machine")
        pa = pyaudio.PyAudio()
        kwargs = dict(
            format=pyaudio.paInt16,
            channels=1,
            rate=rate,
            input=True,
            frames_per_buffer=CHUNK,
        )
        if mic_index is not None:
            kwargs["input_device_index"] = mic_index
        stream = pa.open(**kwargs)
        return pa, stream

    # -- ana dinleme -------------------------------------------------------- #
    def listen(
        self,
        mic_index: Optional[int] = None,
        timeout: float = 8.0,
        phrase_limit: float = 14.0,
        silence: float = 0.9,
        on_level: Optional[Callable[[float], None]] = None,
        on_speech: Optional[Callable[[], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[bytes]:
        """Record speech; a stop event lets push-to-talk end capture on key release."""
        if stop_event and stop_event.is_set():
            return None
        rate = RATE
        pa = None
        stream = None
        try:
            pa, stream = self._open(mic_index, rate)
        except Exception:
            if pa:
                pa.terminate()
            # Cihaz 16k desteklemiyorsa 44.1k ile dene
            rate = 44100
            try:
                pa, stream = self._open(mic_index, rate)
            except Exception:
                return None

        frames: list[bytes] = []
        try:
            if stop_event and stop_event.is_set():
                return None
            if stop_event is not None:
                # Push-to-talk already provides an explicit start and end. Keep
                # the opening syllables and pauses instead of calibrating on speech.
                deadline = time.monotonic() + phrase_limit
                while not stop_event.is_set() and time.monotonic() < deadline:
                    try:
                        data = stream.read(CHUNK, exception_on_overflow=False)
                    except Exception:
                        break
                    frames.append(data)
                    if on_level:
                        on_level(min(1.0, self._rms(data) / 6000.0))
                if not frames:
                    return None
                return sr.AudioData(b"".join(frames), rate, WIDTH).get_wav_data()
            # ortam gürültüsünü ölç
            ambient: list[float] = []
            for _ in range(12):
                if stop_event and stop_event.is_set():
                    return None
                ambient.append(self._rms(stream.read(CHUNK, exception_on_overflow=False)))
            noise = sorted(ambient)[len(ambient) // 2] if ambient else 100.0
            threshold = max(noise * 2.6, 260.0)

            started = False
            start_time = time.time()
            last_voice = 0.0
            speech_hits = 0

            while not (stop_event and stop_event.is_set()):
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                except Exception:
                    break
                level = self._rms(data)
                if on_level:
                    on_level(min(1.0, level / 6000.0))

                now = time.time()
                voiced = level > threshold

                if not started:
                    speech_hits = speech_hits + 1 if voiced else 0
                    if speech_hits >= 2:
                        started = True
                        last_voice = now
                        frames.append(data)
                        if on_speech:
                            on_speech()
                    elif now - start_time > timeout:
                        return None
                else:
                    frames.append(data)
                    if voiced:
                        last_voice = now
                    if stop_event is None and now - last_voice > silence:
                        break
                    if now - start_time > timeout + phrase_limit:
                        break

            if not frames:
                return None
            raw = b"".join(frames)
            return sr.AudioData(raw, rate, WIDTH).get_wav_data()
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                if pa is not None:
                    pa.terminate()
            except Exception:
                pass

    # -- mikrofon testi ----------------------------------------------------- #
    def probe(self, mic_index: Optional[int] = None, seconds: float = 4.0,
              on_level: Optional[Callable[[float], None]] = None) -> dict:
        """Kısa bir kayıt yapıp mikrofonun ses alıp almadığını bildirir."""
        result = {"ok": False, "peak": 0.0, "average": 0.0, "verdict": "no-device", "error": ""}
        pa = None
        stream = None
        rate = RATE
        try:
            pa, stream = self._open(mic_index, rate)
        except Exception:
            if pa:
                pa.terminate()
            rate = 44100
            try:
                pa, stream = self._open(mic_index, rate)
            except Exception as exc:
                result["error"] = type(exc).__name__
                return result

        levels: list[float] = []
        try:
            end = time.time() + max(1.5, float(seconds))
            while time.time() < end:
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                except Exception:
                    break
                rms = self._rms(data)
                levels.append(rms)
                if on_level:
                    on_level(min(1.0, rms / 6000.0))
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                if pa is not None:
                    pa.terminate()
            except Exception:
                pass

        peak = max(levels) if levels else 0.0
        average = (sum(levels) / len(levels)) if levels else 0.0
        if peak < 50:
            verdict = "silent"
        elif peak < 400:
            verdict = "low"
        else:
            verdict = "good"
        return {
            "ok": bool(levels),
            "peak": round(min(1.0, peak / 6000.0), 3),
            "average": round(min(1.0, average / 6000.0), 3),
            "verdict": verdict,
            "error": "",
        }

    # -- metne çevirme ------------------------------------------------------ #
    def transcribe(self, wav: bytes, language: str = "tr-TR") -> str:
        if not SPEECH_RECOGNITION_AVAILABLE:
            raise RuntimeError("SpeechRecognition is not available on this machine")
        audio = sr.AudioData(wav, RATE, WIDTH)
        text = self.recognizer.recognize_google(audio, language=language)
        return re.sub(r"\s+", " ", (text or "").strip())


# --------------------------------------------------------------------------- #
#  Konuşmacı
# --------------------------------------------------------------------------- #
class Speaker:
    def __init__(
        self,
        voice: str = "tr-TR-EmelNeural",
        rate: str = "+0%",
        volume: float = 0.9,
        cloud_consent: bool = False,
        on_start: Optional[Callable[[], None]] = None,
        on_end: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.cloud_consent = bool(cloud_consent)
        self.on_start = on_start
        self.on_end = on_end
        self.on_error = on_error
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stop = threading.Event()
        self._busy = False
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # ---------------------------------------------------------------- #
    def update(self, voice: str | None = None, rate: str | None = None, volume: float | None = None,
               cloud_consent: bool | None = None) -> None:
        if voice:
            self.voice = voice
        if rate:
            self.rate = rate
        if volume is not None:
            self.volume = float(volume)
        if cloud_consent is not None:
            self.cloud_consent = bool(cloud_consent)
            if not self.cloud_consent:
                self.stop()

    def say(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        for piece in self._split(text):
            self._queue.put(piece)

    def stop(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass

    def wait_idle(self, timeout: float = 30.0) -> None:
        end = time.time() + timeout
        while self._busy and time.time() < end:
            time.sleep(0.05)

    # ---------------------------------------------------------------- #
    @staticmethod
    def _split(text: str, limit: int = 220) -> list[str]:
        text = text if len(text) <= 800 else text[:800] + "…"
        parts = re.split(r"(?<=[.!?…])\s+", text)
        chunks: list[str] = []
        current = ""
        for part in parts:
            if len(current) + len(part) + 1 <= limit:
                current = (current + " " + part).strip()
            else:
                if current:
                    chunks.append(current)
                while len(part) > limit:
                    chunks.append(part[:limit])
                    part = part[limit:]
                current = part
        if current:
            chunks.append(current)
        return chunks or [text]

    def _synth(self, text: str) -> str | None:
        if not self.cloud_consent:
            return None
        try:
            import edge_tts

            path = os.path.join(tempfile.gettempdir(), f"helpie_{int(time.time()*1000)}_{abs(hash(text))%9999}.mp3")
            communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
            asyncio.run(communicate.save(path))
            return path
        except Exception:
            return None

    def _speak_local(self, text: str) -> bool:
        """Speak through the installed Windows voice without sending text online."""
        if os.name != "nt":
            return False
        try:
            import comtypes
            from comtypes.client import CreateObject

            comtypes.CoInitialize()
            try:
                voice = CreateObject("SAPI.SpVoice")
                voice.Volume = max(0, min(100, round(self.volume * 100)))
                try:
                    rate = float(str(self.rate).rstrip("%"))
                except (TypeError, ValueError):
                    rate = 0.0
                voice.Rate = max(-10, min(10, round(rate / 10)))
                voice.Speak(text)
                return True
            finally:
                comtypes.CoUninitialize()
        except Exception:
            return False

    def _play_file(self, path: str) -> bool:
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100)
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(max(0.0, min(1.0, self.volume)))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if self._stop.is_set():
                    pygame.mixer.music.stop()
                    return False
                time.sleep(0.05)
            return True
        except Exception:
            return False

    def _run(self) -> None:
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100)
        except Exception:
            pass

        while not self._stop.is_set():
            text = self._queue.get()
            if text is None:
                break
            self._busy = True
            try:
                if self.on_start:
                    self.on_start()
                spoken = False
                if self.cloud_consent:
                    path = self._synth(text)
                    if path:
                        try:
                            spoken = self._play_file(path)
                        finally:
                            try:
                                os.remove(path)
                            except OSError:
                                pass
                if not spoken:
                    spoken = self._speak_local(text)
                if not spoken and self.on_error:
                    self.on_error(
                        "I could not play a spoken reply. Check Windows audio output and the Voice settings."
                    )
            finally:
                self._busy = False
                if self._queue.empty() and self.on_end:
                    self.on_end()

    def close(self) -> None:
        self._stop.set()
        self.stop()
        self._queue.put(None)
