from __future__ import annotations

import io
import sys
import threading
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import voice
import server


class VoiceStopTests(unittest.TestCase):
    def test_transcribe_decodes_wav_and_preserves_rate(self) -> None:
        pcm = b"\x01\x00\x02\x00" * 30
        for rate in (16000, 44100):
            with self.subTest(rate=rate):
                buf = io.BytesIO()
                with wave.open(buf, "wb") as out:
                    out.setnchannels(1)
                    out.setsampwidth(2)
                    out.setframerate(rate)
                    out.writeframes(pcm)
                audio = object()
                recognizer = Mock()
                recognizer.record.return_value = audio
                recognizer.recognize_google.return_value = " hello  world "
                def record(source):
                    with wave.open(source, "rb") as wav:
                        self.assertEqual(wav.getframerate(), rate)
                        self.assertEqual(wav.readframes(wav.getnframes()), pcm)
                    return audio
                recognizer.record.side_effect = record
                fake_sr = types.SimpleNamespace(AudioFile=lambda source: source)
                listener = voice.Listener.__new__(voice.Listener)
                listener.recognizer = recognizer
                with patch.object(voice, "sr", fake_sr), patch.object(voice, "SPEECH_RECOGNITION_AVAILABLE", True):
                    self.assertEqual(listener.transcribe(buf.getvalue(), "tr-TR"), "hello world")
                recognizer.recognize_google.assert_called_once_with(audio, language="tr-TR")

    def test_release_submits_but_cancel_discards_audio(self) -> None:
        class FakeAudio:
            def __init__(self, data, rate, width):
                self.data = data
            def get_wav_data(self):
                return self.data
        for cancel_turn in (False, True):
            with self.subTest(cancel=cancel_turn):
                release, cancel = threading.Event(), threading.Event()
                stream = Mock()
                def read(*_args, **_kwargs):
                    (cancel if cancel_turn else release).set()
                    return b"\x01\x00" * 640
                stream.read.side_effect = read
                listener = voice.Listener.__new__(voice.Listener)
                listener._open = Mock(return_value=(Mock(), stream))
                with patch.object(voice, "sr", types.SimpleNamespace(AudioData=FakeAudio)):
                    result = listener.listen(stop_event=release, cancel_event=cancel)
                self.assertEqual(result is None, cancel_turn)
                stream.close.assert_called_once()

    def test_cancel_ends_ordinary_listening_without_returning_audio(self) -> None:
        cancel = threading.Event()
        stream = Mock()
        reads = [0]
        def read(*_args, **_kwargs):
            reads[0] += 1
            if reads[0] >= 15:
                cancel.set()
            return b"\xff\x7f" * 640
        stream.read.side_effect = read
        listener = voice.Listener.__new__(voice.Listener)
        listener._open = Mock(return_value=(Mock(), stream))
        self.assertIsNone(listener.listen(cancel_event=cancel))
        stream.close.assert_called_once()

    def test_stop_during_synthesis_prevents_fallback_and_allows_next_turn(self) -> None:
        entered, finish, played = threading.Event(), threading.Event(), threading.Event()
        speaker = voice.Speaker(cloud_consent=True)
        def synth(_text):
            entered.set()
            finish.wait(3)
            return None
        try:
            with patch.object(speaker, "_synth", side_effect=synth), \
                 patch.object(speaker, "_speak_local", side_effect=lambda *_: played.set() or True) as local:
                speaker.say("First.")
                self.assertTrue(entered.wait(2))
                speaker.stop()
                finish.set()
                speaker.wait_idle(3)
                local.assert_not_called()
                speaker.cloud_consent = False
                speaker.say("Second.")
                self.assertTrue(played.wait(2))
                speaker.wait_idle(3)
                self.assertEqual(local.call_count, 1)
        finally:
            finish.set()
            speaker.close()

    def test_local_speech_is_purged_when_cancelled(self) -> None:
        cancel = threading.Event()
        sapi = Mock()
        sapi.WaitUntilDone.side_effect = lambda _ms: cancel.set() or False
        comtypes = types.ModuleType("comtypes")
        comtypes.CoInitialize = Mock()
        comtypes.CoUninitialize = Mock()
        client = types.ModuleType("comtypes.client")
        client.CreateObject = Mock(return_value=sapi)
        speaker = voice.Speaker.__new__(voice.Speaker)
        speaker.volume = 0.9
        speaker.rate = "+0%"
        speaker._stop = threading.Event()
        with patch.object(voice.os, "name", "nt"), \
             patch.dict(sys.modules, {"comtypes": comtypes, "comtypes.client": client}):
            self.assertFalse(speaker._speak_local("Example", cancel))
        self.assertEqual(sapi.Speak.call_args_list[0].args, ("Example", 1))
        self.assertEqual(sapi.Speak.call_args_list[1].args, ("", 3))
        comtypes.CoUninitialize.assert_called_once()

    def test_cancel_while_transcribing_discards_result(self) -> None:
        app = server.App.__new__(server.App)
        app._no_voice = False
        app.cfg = {"cloud_speech_consent": True, "language": "tr-TR"}
        app._listen_lock = threading.Lock()
        app._voice_turn_guard = threading.Lock()
        app._push_to_talk_stop = threading.Event()
        app._push_to_talk_stop.set()
        app._closing = False
        app._voice_level = 0.0
        app.bus = Mock()
        app.push_state = Mock()
        app.speaker = Mock()
        app.listener = Mock()
        app.listener.listen.return_value = b"audio"
        entered, finish = threading.Event(), threading.Event()
        def transcribe(*_args):
            entered.set()
            finish.wait(3)
            return "do something"
        app.listener.transcribe.side_effect = transcribe
        app.reply = Mock()
        cancel = threading.Event()
        app._voice_cancel = cancel
        worker = threading.Thread(target=app.listen, args=("chat", cancel))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            app.cancel_voice()
        finally:
            finish.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        app.reply.assert_not_called()
        app.speaker.stop.assert_called_once()

    def test_stop_marks_all_active_turns_cancelled(self) -> None:
        app = server.App.__new__(server.App)
        app._turns_lock = threading.Lock()
        first, second = threading.Event(), threading.Event()
        app._active_turns = {first, second}
        app.cancel_turns()
        self.assertTrue(first.is_set())
        self.assertTrue(second.is_set())

    def test_stop_endpoint_requests_capture_shutdown(self) -> None:
        app = Mock()
        app._live_capture_lock = threading.Lock()
        handler = server.Handler.__new__(server.Handler)
        handler.app = app
        handler.path = "/api/stop"
        handler._trusted_local_request = Mock(return_value=True)
        handler._authorized_api = Mock(return_value=True)
        handler._body = Mock(return_value={})
        handler._json = Mock()
        shell = types.ModuleType("shell")
        shell.request = Mock(return_value=True)
        shell.stop_live_capture = Mock()
        with patch.dict(sys.modules, {"shell": shell}):
            handler.do_POST()
        app.cancel_turns.assert_called_once()
        app.cancel_voice.assert_called_once()
        shell.request.assert_called_once_with("hide-overlay")
        shell.stop_live_capture.assert_called_once()
        handler._json.assert_called_once_with({"ok": True})


if __name__ == "__main__":
    unittest.main()
