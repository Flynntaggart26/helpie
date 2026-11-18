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
                           ("open_app", [])):
            with self.subTest(name=name, args=args):
                self.assertIsNone(review_model_action(name, args))

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


if __name__ == "__main__":
    unittest.main()
