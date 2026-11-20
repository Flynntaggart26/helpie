from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from brain import SCREEN_REQUEST_RE, VISUAL_REQUEST_RE, _parse_visual_response  # noqa: E402
from visual_notes import _normalize_visual_items  # noqa: E402


class VisualAnnotationTests(unittest.TestCase):
    def test_explanation_must_match_the_spoken_answer(self) -> None:
        payload = {"version": 1, "items": [
            {"kind": "pin", "x": 0.2, "y": 0.3, "explanation": "The first point is here."},
            {"kind": "pin", "x": 0.4, "y": 0.5, "explanation": "Invented phrase"},
        ]}
        answer, items = _parse_visual_response(
            "The first point is here. [[HELPIE_VISUAL]]" + json.dumps(payload)
        )
        self.assertEqual(answer, "The first point is here.")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["explanation"], "The first point is here.")

    def test_accepts_only_bounded_pin_callout_and_arrow(self) -> None:
        payload = {
            "version": 1,
            "items": [
                {"kind": "pin", "x": 0.25, "y": 0.5, "label": "OK\nbutton"},
                {"kind": "callout", "x": 0.6, "y": 0.5, "number": 2,
                 "label": "second item"},
                {"kind": "arrow", "x1": 0.2, "y1": 0.2,
                 "x2": 0.9, "y2": 0.8, "label": ""},
            ],
        }
        text, items = _parse_visual_response(
            "The button is near the center. [[HELPIE_VISUAL]]" + json.dumps(payload)
        )

        self.assertEqual(text, "The button is near the center.")
        self.assertEqual([item["kind"] for item in items],
                         ["pin", "callout", "arrow"])
        self.assertEqual(items[0]["label"], "OKbutton")
        self.assertEqual(items[1]["number"], 2)

    def test_rejects_out_of_bounds_and_non_finite_coordinates(self) -> None:
        payload = {"version": 1, "items": [
            {"kind": "pin", "x": 1.1, "y": 0.5},
            {"kind": "rect", "x": 0.9, "y": 0.5, "width": 0.2, "height": 0.2},
            {"kind": "arrow", "x1": 0.1, "y1": float("nan"), "x2": 0.8, "y2": 0.8},
        ]}
        text, items = _parse_visual_response(
            "Here is the answer. [[HELPIE_VISUAL]]" + json.dumps(payload)
        )

        self.assertEqual(text, "Here is the answer.")
        self.assertEqual(items, [])

    def test_invalid_or_executable_payload_never_reaches_renderer(self) -> None:
        for payload in (
            "not-json",
            '{"version":1,"items":[{"kind":"pin","x":0.5,"y":0.5,"html":"<script>"}]}',
            '{"version":1,"items":[{"kind":"pin","x":0.5,"y":0.5}]} trailing text',
            '{"items":[{"kind":"pin","x":0.5,"y":0.5}]}',
            '{"version":2,"items":[{"kind":"pin","x":0.5,"y":0.5}]}',
            '{"version":true,"items":[{"kind":"pin","x":0.5,"y":0.5}]}',
        ):
            with self.subTest(payload=payload):
                text, items = _parse_visual_response(
                    "Answer. [[HELPIE_VISUAL]]" + payload
                )
                self.assertEqual(text, "Answer.")
                self.assertEqual(items, [])

    def test_screen_and_visual_requests_are_detected_in_english_and_turkish(self) -> None:
        for request in ("What do you see on my screen?", "Highlight the red button",
                        "Ekranımda ne görüyorsun?", "Şu butonu işaretle"):
            with self.subTest(request=request):
                self.assertRegex(request, SCREEN_REQUEST_RE)
        self.assertRegex("circle the chart legend", VISUAL_REQUEST_RE)

    def test_screen_questions_and_solutions_require_screen_reference(self) -> None:
        for request in ("ekrandaki soruyu çöz", "ekranımdaki matematik sorusunu çöz",
                        "ekrandaki soruyu coz", "solve the question on my screen",
                        "ekranımda ne var", "ekranımda neler var",
                        "whats on my screen", "what's on my screen", "view my screen",
                        "Ekranımda ne görüyorsun", "ekranımdaki yazıyı oku"):
            with self.subTest(request=request):
                self.assertRegex(request, SCREEN_REQUEST_RE)
        for request in ("bu soruyu çöz", "solve this problem", "merhaba", "ekranı kapatınca ne olur"):
            with self.subTest(request=request):
                self.assertNotRegex(request, SCREEN_REQUEST_RE)

    def test_underline_is_bounded_and_nonzero(self) -> None:
        payload = {"version": 1, "items": [
            {"kind": "underline", "x1": 0.1, "y1": 0.3, "x2": 0.8, "y2": 0.3},
            {"kind": "underline", "x1": 0.2, "y1": 0.3, "x2": 0.2, "y2": 0.3},
            {"kind": "underline", "x1": 0.1, "y1": 0.3, "x2": 1.2, "y2": 0.3},
        ]}
        _, items = _parse_visual_response("Answer. [[HELPIE_VISUAL]]" + json.dumps(payload))
        self.assertEqual([item["kind"] for item in items], ["underline"])
        self.assertEqual(_normalize_visual_items(items), items)


if __name__ == "__main__":
    unittest.main()
