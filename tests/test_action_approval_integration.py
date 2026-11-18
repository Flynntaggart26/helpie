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


if __name__ == "__main__":
    unittest.main()
