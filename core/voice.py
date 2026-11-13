"""Ses: mikrofon dinleme (STT) ve konuşma (TTS)."""
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

import pyaudio
import speech_recognition as sr

CHUNK = 640
RATE = 16000
WIDTH = 2


# --------------------------------------------------------------------------- #
#  Mikrofon listesi
# --------------------------------------------------------------------------- #
def list_microphones() -> list[dict]:
    """Kullanılabilir mikrofonları (index, ad) olarak döndürür."""
    out: list[dict] = []
    try:
        for index, name in enumerate(sr.Microphone.list_microphone_names()):
            out.append({"index": index, "name": name})
    except Exception:
        pass
    return out


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
    ) -> Optional[bytes]:
        """Konuşmayı kaydeder. Sessizlikte None döner. 16k/16bit mono WAV döndürür."""
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
            # ortam gürültüsünü ölç
            ambient: list[float] = []
            for _ in range(12):
                ambient.append(self._rms(stream.read(CHUNK, exception_on_overflow=False)))
            noise = sorted(ambient)[len(ambient) // 2] if ambient else 100.0
            threshold = max(noise * 2.6, 260.0)

            started = False
            start_time = time.time()
            last_voice = 0.0
            speech_hits = 0

            while True:
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
                    if now - last_voice > silence:
                        break
                    if now - start_time > timeout + phrase_limit:
                        break

            if not frames:
                return None
            raw = b"".join(frames)
            if rate != RATE:
                try:
                    import audioop

                    raw, _ = audioop.ratecv(raw, WIDTH, 1, rate, RATE, None)
                except Exception:
                    pass
            return sr.AudioData(raw, RATE, WIDTH).get_wav_data()
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

    # -- metne çevirme ------------------------------------------------------ #
    def transcribe(self, wav: bytes, language: str = "tr-TR") -> str:
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
        on_start: Optional[Callable[[], None]] = None,
        on_end: Optional[Callable[[], None]] = None,
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.on_start = on_start
        self.on_end = on_end
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stop = threading.Event()
        self._busy = False
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # ---------------------------------------------------------------- #
    def update(self, voice: str | None = None, rate: str | None = None, volume: float | None = None) -> None:
        if voice:
            self.voice = voice
        if rate:
            self.rate = rate
        if volume is not None:
            self.volume = float(volume)

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
        try:
            import edge_tts

            path = os.path.join(tempfile.gettempdir(), f"helpie_{int(time.time()*1000)}_{abs(hash(text))%9999}.mp3")
            communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
            asyncio.run(communicate.save(path))
            return path
        except Exception:
            return None

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
                path = self._synth(text)
                if path:
                    try:
                        import pygame

                        if not pygame.mixer.get_init():
                            pygame.mixer.init(frequency=44100)
                        pygame.mixer.music.load(path)
                        pygame.mixer.music.set_volume(self.volume)
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy():
                            if self._stop.is_set():
                                pygame.mixer.music.stop()
                                break
                            time.sleep(0.05)
                    except Exception:
                        pass
                    finally:
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                else:
                    # internet yok / edge-tts çalışmadı: kısa süre bekle, balon görünsün
                    time.sleep(min(4.0, max(1.0, len(text) / 22)))
            finally:
                self._busy = False
                if self._queue.empty() and self.on_end:
                    self.on_end()

    def close(self) -> None:
        self._stop.set()
        self.stop()
        self._queue.put(None)
