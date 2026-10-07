"""AI 最小场景上下文与数据预览测试。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from bsa.planner.context_builder import MAX_CONTEXT_OBJECTS, ContextBuilder
from tests.support import make_object, make_scene


class ContextBuilderTests(unittest.TestCase):
    def test_named_objects_only_and_public_fields_are_sent(self) -> None:
        snapshot = make_scene().read_snapshot()
        built = ContextBuilder().build("让 Lamp 靠近 Desk，但不要移动 Desk", snapshot)
        self.assertEqual(built.object_ids, ("desk-id", "lamp-id"))
        self.assertEqual(built.payload["unit_scale"], 1.0)
        self.assertEqual(
            set(built.payload["objects"][0]),
            {"object_id", "name", "type", "location", "dimensions", "locked"},
        )
        serialized = str(built.payload)
        self.assertNotIn("matrix_world", serialized)
        self.assertNotIn("bbox", serialized)
        self.assertNotIn("parent", serialized)
        self.assertIn("2 个对象摘要", built.preview_text)
        self.assertIn("场景单位比例：1.0", built.preview_text)
        self.assertIn("ID=desk-id", built.preview_text)
        self.assertIn("位置=[0.0, 0.0, 0.5]", built.preview_text)
        self.assertIn("尺寸=[4.0, 2.0, 1.0]", built.preview_text)

    def test_ascii_object_names_match_whole_names_not_substrings(self) -> None:
        from bsa.application.memory_scene import MemoryScenePort

        objects = (
            make_object("lamp-id", "Lamp", (0, 0, 0), (1, 1, 1)),
            make_object("shade-id", "Lampshade", (0, 0, 0), (1, 1, 1)),
        )
        snapshot = MemoryScenePort(objects).read_snapshot()
        built = ContextBuilder().build("把 Lampshade 锁定", snapshot)
        self.assertEqual(built.object_ids, ("shade-id",))

    def test_payload_numbers_are_canonicalized_for_review_and_request(self) -> None:
        from bsa.application.memory_scene import MemoryScenePort

        snapshot = MemoryScenePort(
            (
                make_object(
                    "precise-id",
                    "Precise",
                    (0.123456789, -0.0000004, 0.5),
                    (0.4000000059604645, 1.23456789, 2.0),
                ),
            )
        ).read_snapshot()
        built = ContextBuilder().build("锁定 Precise", snapshot)
        summary = built.payload["objects"][0]
        self.assertEqual(summary["location"], [0.123457, -0.0, 0.5])
        self.assertEqual(summary["dimensions"], [0.4, 1.234568, 2.0])
        self.assertIn("尺寸=[0.4, 1.234568, 2.0]", built.preview_text)

    def test_unnamed_instruction_uses_visible_stable_bounded_fallback(self) -> None:
        objects = tuple(
            make_object(f"id-{index:02d}", f"Object {index:02d}", (0.0, 0.0, 0.0), (1, 1, 1))
            for index in reversed(range(MAX_CONTEXT_OBJECTS + 5))
        )
        hidden = replace(objects[0], object_id="hidden-id", name="Hidden", visible=False)
        from bsa.application.memory_scene import MemoryScenePort

        snapshot = MemoryScenePort(objects + (hidden,)).read_snapshot()
        built = ContextBuilder().build("把这些物体整理得更紧凑", snapshot)
        self.assertEqual(len(built.object_ids), MAX_CONTEXT_OBJECTS)
        self.assertEqual(built.object_ids, tuple(sorted(built.object_ids)))
        self.assertNotIn("hidden-id", built.object_ids)
        self.assertEqual(built.omitted_object_count, 5)

    def test_empty_or_oversized_instruction_is_rejected(self) -> None:
        snapshot = make_scene().read_snapshot()
        for instruction in ("", "x" * 501):
            with self.subTest(length=len(instruction)), self.assertRaises(ValueError):
                ContextBuilder().build(instruction, snapshot)


if __name__ == "__main__":
    unittest.main()
