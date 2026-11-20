from __future__ import annotations

import sys
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import brain
import shell


class ApprovalIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.llm = Mock()
        self.llm.available = True
        self.llm.chat.return_value = '[[ACTION]] {"name":"open_app","args":{"app":"Calculator"}}'
        with patch.object(brain, "LlmBrain", return_value=self.llm), \
             patch.object(brain.memory, "as_prompt", return_value=""):
            self.agent = brain.Brain({})
        self.agent._dispatch_plugin_command = Mock(return_value="")
        self.audit = patch.object(brain.audit, "log")
        self.audit.start()
        self.addCleanup(self.audit.stop)
        self.dispatch = patch.object(self.agent, "_dispatch", return_value="Opened.")
        self.action = self.dispatch.start()
        self.addCleanup(self.dispatch.stop)

    def test_companion_screen_solution_requests_and_renders_visual_answer(self) -> None:
        self.agent.cfg.update(screen_context_consent=True, companion_live_view_consent=True)
        self.llm.provider = "gemini"
        items = [{"kind": "underline", "x1": 0.1, "y1": 0.3, "x2": 0.8, "y2": 0.3},
                 {"kind": "equation", "x": 0.1, "y": 0.6, "text": "x = 2"}]
        self.llm.vision.return_value = "The answer is two. [[HELPIE_VISUAL]]" + json.dumps({"version": 1, "items": items})
        self.agent.on_event = Mock()
        with patch.object(shell, "capture_latest_frame", return_value=(b"synthetic", {"captured_at_ms": "0", "target": "test"})) as capture, \
             patch.object(shell, "live_capture_status", return_value={"active": True, "companion_active": True}):
            reply = self.agent.handle("ekrandaki soruyu çöz", source="companion")
        self.assertEqual(reply, "The answer is two.")
        capture.assert_called_once()
        self.assertTrue(self.llm.vision.call_args.kwargs["annotate"])
        events = [call.args[0] for call in self.agent.on_event.call_args_list]
        visual = next(event for event in events if event.get("type") == "visual_annotations")
        self.assertEqual([item["kind"] for item in visual["items"]], ["underline", "equation"])

    def test_vague_question_does_not_capture_a_companion_frame(self) -> None:
        with patch.object(shell, "capture_latest_frame") as capture:
            self.agent.handle("bu soruyu çöz", source="companion")
        capture.assert_not_called()
        self.llm.vision.assert_not_called()

    def test_approval_executes_once_and_cancel_prevents_execution(self) -> None:
        self.assertIn("Calculator", self.agent.handle("explain quantum theory"))
        self.action.assert_not_called()
        self.assertEqual(self.agent.handle("yes"), "Opened.")
        self.action.assert_called_once_with("open_app", {"app": "Calculator"})
        self.agent.handle("explain quantum theory")
        self.assertIn("cancelled", self.agent.handle("no").lower())
        self.action.assert_called_once()

    def test_expired_proposal_is_not_executed(self) -> None:
        with patch.object(brain.time, "monotonic", return_value=100):
            self.agent.handle("explain quantum theory")
        with patch.object(brain.time, "monotonic", return_value=161):
            self.assertIn("expired", self.agent.handle("yes").lower())
        self.action.assert_not_called()

    def test_cancel_invalidates_a_delayed_model_response(self) -> None:
        started, release = threading.Event(), threading.Event()
        def delayed(_prompt: str) -> str:
            started.set()
            if not release.wait(3):
                raise RuntimeError("test did not release model")
            return '[[ACTION]] {"name":"open_app","args":{"app":"Calculator"}}'
        self.llm.chat.side_effect = delayed
        replies = []
        worker = threading.Thread(target=lambda: replies.append(self.agent.handle("explain quantum theory")))
        worker.start()
        try:
            self.assertTrue(started.wait(2))
            self.agent.cancel_model_proposal()
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertIn("cancelled", replies[0].lower())
        self.assertIsNone(self.agent._model_proposal)
        self.action.assert_not_called()

    def test_stop_during_screen_picker_prevents_provider_transfer(self) -> None:
        self.agent.cfg["screen_context_consent"] = True
        self.agent.llm.vision = Mock()
        started, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        def capture():
            started.set()
            release.wait(3)
            return b"fake image", {"captured_at": "now", "target": "test", "active_window": ""}
        replies = []
        with patch.object(brain.actions, "capture_screen_context", side_effect=capture):
            worker = threading.Thread(target=lambda: replies.append(
                self.agent.handle("what is on my screen", cancel_event=cancelled)))
            worker.start()
            try:
                self.assertTrue(started.wait(2))
                cancelled.set()
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertIn("cancelled", replies[0].lower())
        self.agent.llm.vision.assert_not_called()

    def test_stop_during_provider_request_discards_screen_response(self) -> None:
        self.agent.cfg["screen_context_consent"] = True
        self.agent.llm.provider = "gemini"
        started, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        def vision(*_args, **_kwargs):
            started.set()
            release.wait(3)
            return "old answer"
        self.agent.llm.vision = Mock(side_effect=vision)
        replies = []
        captured = (b"fake image", {"captured_at": "now", "target": "test", "active_window": ""})
        with patch.object(brain.actions, "capture_screen_context", return_value=captured):
            worker = threading.Thread(target=lambda: replies.append(
                self.agent.handle("what is on my screen", cancel_event=cancelled)))
            worker.start()
            try:
                self.assertTrue(started.wait(2))
                cancelled.set()
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(replies, ["Screen request cancelled."])

    def test_direct_action_uses_target_validation(self) -> None:
        self.assertIn("could not", self.agent._dispatch_direct_desktop("open_app", {"app": "a\u202eb"}).lower())
        self.action.assert_not_called()
        self.assertEqual(self.agent._dispatch_direct_desktop("open_app", {"app": "Calculator"}), "Opened.")
        self.action.assert_called_once_with("open_app", {"app": "Calculator"})

    def test_user_commands_route_through_direct_policy(self) -> None:
        with patch.object(brain.action_policy, "review_direct_action", wraps=brain.action_policy.review_direct_action) as review:
            self.assertEqual(self.agent.handle("open calculator"), "Opened.")
            review.assert_called_once()
            self.assertEqual(review.call_args.args[0], "open_app")
        self.action.assert_called_once()

    def test_find_duplicates_is_always_a_preview(self) -> None:
        result = {"folder": "Downloads", "groups": 1, "removed": 1,
                  "freed_bytes": 10, "details": ["Duplicate: example.txt"]}
        with patch.object(self.agent, "_resolve_folder", return_value=Path("Downloads")), \
             patch.object(brain.actions, "remove_duplicates", return_value=result) as find:
            reply = self.agent.handle("find duplicates in downloads")
        find.assert_called_once_with(Path("Downloads"), True)
        self.assertIn("No files were deleted", reply)

    def test_file_removal_is_not_sent_to_model_or_reported_as_done(self) -> None:
        for command in ("delete this file", "remove these files", "dosyayı sil", "klasörü kaldır"):
            with self.subTest(command=command):
                reply = self.agent.handle(command)
                self.assertIn("not available yet", reply)
                self.assertIn("haven't moved or deleted", reply)
        self.llm.chat.assert_not_called()
        self.action.assert_not_called()

    def test_deleted_files_list_is_honest_while_recycle_is_unavailable(self) -> None:
        for command in ("show files you deleted", "show deleted files", "sildiğin dosyaları listele"):
            with self.subTest(command=command):
                self.assertIn("no completed", self.agent.handle(command).lower())
        self.llm.chat.assert_not_called()

    def test_deleted_files_list_uses_only_session_receipts(self) -> None:
        app = Mock()
        app.recycle_broker.available.return_value = True
        app.recycle_broker.recent.return_value = ["example.txt", "folder/report.pdf"]
        self.agent._app = app
        reply = self.agent.handle("show files you deleted")
        self.assertIn("example.txt", reply)
        self.assertIn("folder/report.pdf", reply)
        self.llm.chat.assert_not_called()

    def test_recycle_bin_requires_confirmation_and_executes_once(self) -> None:
        self.dispatch.stop()
        with patch.object(brain.actions, "empty_recycle_bin", return_value="Done") as empty:
            self.assertIn("Permanently", self.agent.handle("empty recycle bin"))
            empty.assert_not_called()
            self.assertEqual(self.agent.handle("yes"), "Done")
            empty.assert_called_once_with()
            self.agent.handle("empty recycle bin")
            self.assertIn("cancelled", self.agent.handle("no").lower())
            empty.assert_called_once()

    def test_recycle_bin_cannot_run_in_plan_or_routine_without_confirmation(self) -> None:
        self.dispatch.stop()
        with patch.object(brain.actions, "empty_recycle_bin") as empty:
            self.agent._in_plan = True
            self.assertIn("separately", self.agent.handle("empty recycle bin"))
            self.agent._in_plan = False
            self.assertIn("confirm", self.agent._execute_routine_step("empty_recycle_bin", {}))
            empty.assert_not_called()

    def test_recycle_bin_proposal_expires_and_stop_cancels(self) -> None:
        self.dispatch.stop()
        with patch.object(brain.actions, "empty_recycle_bin") as empty:
            with patch.object(brain.time, "monotonic", return_value=100):
                self.agent.handle("empty recycle bin")
            with patch.object(brain.time, "monotonic", return_value=161):
                self.assertIn("expired", self.agent.handle("yes").lower())
            self.agent.handle("empty recycle bin")
            self.agent.cancel_model_proposal()
            self.assertIsNone(self.agent._model_proposal)
            empty.assert_not_called()

    def test_recycle_bin_reports_failure_when_windows_command_fails(self) -> None:
        result = Mock(returncode=1)
        with patch.object(brain.actions.subprocess, "run", return_value=result), \
             patch.object(brain.actions.audit, "log") as log:
            self.assertIn("could not", brain.actions.empty_recycle_bin().lower())
            log.assert_called_once_with("Emptied the recycle bin", ok=False)

    def test_recycle_bin_reports_success_only_after_successful_command(self) -> None:
        result = Mock(returncode=0)
        with patch.object(brain.actions.subprocess, "run", return_value=result), \
             patch.object(brain.actions, "_audit") as log:
            self.assertEqual(brain.actions.empty_recycle_bin(), "Recycle Bin emptied.")
            log.assert_called_once_with("Emptied the recycle bin")


if __name__ == "__main__":
    unittest.main()
