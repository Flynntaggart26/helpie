from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from action_policy import confirmation, review_direct_action, review_model_action


class ActionPolicyTests(unittest.TestCase):
    def test_single_action_preview_preserves_target(self) -> None:
        proposal = review_model_action("open_app", {"app": "Calculator"})
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.preview, "Open app: Calculator")
        self.assertEqual(proposal.args, {"app": "Calculator"})

    def test_rejects_unknown_chains_and_invalid_targets(self) -> None:
        for name, args in (("plan", {"steps": []}), ("open_app", {"app": "x", "other": 1}),
                           ("open_app", {"app": "x\nrun"}), ("close_app", {"app": "x" * 81}),
                           ("open_app", {"app": "safe\u202eevil"}),
                           ("open_app", {"app": "https://example.com"}),
                           ("open_app", {"app": "C:\\temp\\x.exe"}),
                           ("open_app", [])):
            with self.subTest(name=name, args=args):
                self.assertIsNone(review_model_action(name, args))

    def test_external_actions_are_bounded_and_show_exact_target(self) -> None:
        link = review_direct_action("open_url", {"url": "https://example.com/Path?A=B"})
        self.assertEqual(link.risk, "external_communication")
        self.assertIn("https://example.com/Path?A=B", link.preview)
        search = review_direct_action("web_search", {"query": "example query", "engine": "youtube"})
        self.assertIn("example query", search.preview)
        self.assertIn("Youtube", search.preview)
        for url in ("javascript:alert(1)", "https://user:password@example.com", "https://example.com\\@evil.test",
                    "https://example.com/\u202eevil", "https://example.com:99999"):
            self.assertIsNone(review_direct_action("open_url", {"url": url}))
        self.assertIsNone(review_direct_action("web_search", {"query": "test", "engine": "other"}))

    def test_confirmation_is_an_entire_response(self) -> None:
        self.assertEqual(confirmation(" Evet! "), "yes")
        self.assertEqual(confirmation("cancel"), "no")
        self.assertIsNone(confirmation("yes but do not do it"))
        self.assertIsNone(confirmation("nobody asked"))

    def test_recycle_bin_is_destructive_and_only_direct(self) -> None:
        proposal = review_direct_action("empty_recycle_bin", {})
        self.assertEqual(proposal.risk, "destructive")
        self.assertIn("Permanently", proposal.preview)
        self.assertIsNone(review_model_action("empty_recycle_bin", {}))
        self.assertIsNone(review_direct_action("empty_recycle_bin", {"extra": True}))

    def test_screenshot_is_sensitive_and_only_direct(self) -> None:
        proposal = review_direct_action("screenshot", {})
        self.assertEqual(proposal.risk, "sensitive_local_data")
        self.assertIn("all monitors", proposal.preview)
        self.assertIsNone(review_direct_action("screenshot", {"monitor": 1}))
        self.assertIsNone(review_model_action("screenshot", {}))


if __name__ == "__main__":
    unittest.main()
