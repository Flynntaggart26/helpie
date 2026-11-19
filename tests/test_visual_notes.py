from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import visual_notes  # noqa: E402


def stroke(points: list[dict[str, float]] | None = None) -> dict:
    return {"color": "#55d6ff", "size": 4, "points": points or [{"x": 0.1, "y": 0.2}]}


class VisualNoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.file_patch = patch.object(
            visual_notes, "NOTES_FILE", Path(self.temp_dir.name) / "visual_notes.json")
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)

    def test_edited_geometry_reopens_with_constraints(self) -> None:
        item = {"kind": "geometry", "x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8,
                "objects": [
                    {"kind": "point", "x": 0.35, "y": 0.45, "label": "A"},
                    {"kind": "segment", "x1": 0.2, "y1": 0.4, "x2": 0.8, "y2": 0.4, "label": "line"},
                    {"kind": "circle", "cx": 0.6, "cy": 0.5, "radius": 0.2, "label": "C"},
                    {"kind": "polygon", "points": [[0.1, 0.1], [0.8, 0.2], [0.4, 0.9]], "label": "P"},
                ], "constraints": [{"kind": "horizontal", "objects": [1]}]}
        saved = visual_notes.save_note("", "Geometry", [], [item])
        restored = visual_notes.get_note(saved["id"])
        self.assertEqual(restored["visual_items"], [item])

    def test_create_list_reopen_and_edit_preserves_note_id(self) -> None:
        created = visual_notes.save_note("", "Sketch", [stroke()])

        self.assertEqual(visual_notes.get_note(created["id"]), created)
        self.assertEqual(visual_notes.list_notes(), [{
            "id": created["id"], "title": "Sketch", "updated_at": created["updated_at"],
            "stroke_count": 1, "visual_count": 0,
        }])

        updated = visual_notes.save_note(created["id"], "Updated sketch", [])
        self.assertEqual(updated["id"], created["id"])
        self.assertEqual(updated["title"], "Updated sketch")
        self.assertEqual(updated["strokes"], [])

    def test_rejects_invalid_schema_coordinates_colors_and_screen_image_fields(self) -> None:
        invalid_payloads = [
            [{"kind": "pin", "x": 0.5, "y": 0.5}],
            [{"color": ["#fff"], "size": 4, "points": [{"x": 0.1, "y": 0.2}]}],
            [{"color": "red", "size": 4, "points": [{"x": 0.1, "y": 0.2}]}],
            [{"color": "#55d6ff", "size": True, "points": [{"x": 0.1, "y": 0.2}]}],
            [{"color": "#55d6ff", "size": 4, "points": [{"x": 1.1, "y": 0.2}]}],
            [{"color": "#55d6ff", "size": 4, "points": [{"x": float("nan"), "y": 0.2}]}],
            [{"color": "#55d6ff", "size": 4, "points": [{"x": 0.1, "y": 0.2}],
              "image": "data:image/png;base64,private"}],
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                visual_notes.save_note("", "Invalid", payload)

    def test_enforces_stroke_point_note_and_store_limits(self) -> None:
        with patch.object(visual_notes, "MAX_STROKES", 1):
            with self.assertRaises(ValueError):
                visual_notes.save_note("", "Too many strokes", [stroke(), stroke()])

        with patch.object(visual_notes, "MAX_POINTS_PER_STROKE", 1):
            with self.assertRaises(ValueError):
                visual_notes.save_note("", "Too many points", [stroke([
                    {"x": 0.1, "y": 0.2}, {"x": 0.2, "y": 0.3},
                ])])

        with patch.object(visual_notes, "MAX_POINTS_TOTAL", 1):
            with self.assertRaises(ValueError):
                visual_notes.save_note("", "Too many total points", [stroke([
                    {"x": 0.1, "y": 0.2}, {"x": 0.2, "y": 0.3},
                ])])

        with patch.object(visual_notes, "MAX_NOTES", 1):
            visual_notes.save_note("", "First", [])
            with self.assertRaises(ValueError):
                visual_notes.save_note("", "Second", [])

        limited_file = Path(self.temp_dir.name) / "limited.json"
        with patch.object(visual_notes, "NOTES_FILE", limited_file), \
                patch.object(visual_notes, "MAX_STORE_BYTES", 10):
            with self.assertRaises(ValueError):
                visual_notes.save_note("", "Too large", [])

    def test_delete_and_missing_or_corrupt_records_fail_closed(self) -> None:
        note = visual_notes.save_note("", "Delete me", [])
        self.assertTrue(visual_notes.delete_note(note["id"]))
        self.assertFalse(visual_notes.delete_note(note["id"]))
        self.assertIsNone(visual_notes.get_note("../outside"))

        visual_notes.NOTES_FILE.write_text("not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            visual_notes.list_notes()


if __name__ == "__main__":
    unittest.main()
