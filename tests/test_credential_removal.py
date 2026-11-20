from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import config
import server


class CredentialRemovalTests(unittest.TestCase):
    def test_removal_persists_and_preserves_other_keys(self) -> None:
        for field in server.REMOVABLE_CREDENTIALS:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "settings.json"
                app = server.App.__new__(server.App)
                app.cfg = dict(config.DEFAULTS, api_key="gemini", openai_key="router",
                               groq_speech_key="speech", wake_word_access_key="wake",
                               groq_speech_consent=True, wake_word=True)
                app._live_capture_status = {"active": False}
                app.brain, app.speaker, app.bus = Mock(), Mock(), Mock()
                app._stop_wake_word, app._start_wake_word = Mock(), Mock()
                protector = Mock()
                protector.protect.side_effect = lambda s: "encrypted:" + s
                with patch.object(config, "DATA_DIR", Path(directory)), \
                     patch.object(config, "SETTINGS_PATH", path), patch.object(config, "dpapi", protector), \
                     patch.object(server.actions, "set_background_mode"), \
                     patch.object(server.actions, "set_screen_context_consent"), \
                     patch.object(server.actions, "set_screen_capture_target"), \
                     patch.object(server.actions, "weather", return_value=""), \
                     patch.object(server.autostart, "enabled", return_value=False):
                    public = app.update_settings({}, broadcast=False, clear_credential=field)
                    saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(app.cfg[field], "")
                self.assertNotIn(field, saved)
                self.assertNotIn(field + "_enc", saved)
                self.assertNotIn(field, public)
                for other in server.REMOVABLE_CREDENTIALS - {field}:
                    self.assertTrue(saved.get(other + "_enc"))
                if field == "wake_word_access_key":
                    self.assertFalse(app.cfg["wake_word"])
                if field == "groq_speech_key":
                    self.assertFalse(app.cfg["groq_speech_consent"])
                if field == "api_key":
                    self.assertTrue(app.cfg["api_key_env_disabled"])

    def test_removed_gemini_key_does_not_reappear_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"api_key_env_disabled": true}', encoding="utf-8")
            with patch.object(config, "DATA_DIR", Path(directory)), \
                 patch.object(config, "SETTINGS_PATH", path), \
                 patch.dict(config.os.environ, {"GEMINI_API_KEY": "environment-key"}):
                self.assertEqual(config.load()["api_key"], "")

    def test_endpoint_rejects_unknown_credential(self) -> None:
        handler = server.Handler.__new__(server.Handler)
        handler.app = Mock()
        handler.path = "/api/settings/credentials/remove"
        handler._trusted_local_request = Mock(return_value=True)
        handler._authorized_api = Mock(return_value=True)
        handler._body = Mock(return_value={"credential": "other"})
        handler._json = Mock()
        handler.do_POST()
        handler.app.update_settings.assert_not_called()
        self.assertEqual(handler._json.call_args.args[1], 400)

    def test_save_failure_does_not_clear_in_memory_credential(self) -> None:
        app = server.App.__new__(server.App)
        app.cfg = dict(config.DEFAULTS, groq_speech_key="sample", groq_speech_consent=True)
        with patch.object(config, "save", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                app.update_settings({}, clear_credential="groq_speech_key")
        self.assertEqual(app.cfg["groq_speech_key"], "sample")
        self.assertTrue(app.cfg["groq_speech_consent"])


if __name__ == "__main__":
    unittest.main()
