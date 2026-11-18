from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import brain


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
