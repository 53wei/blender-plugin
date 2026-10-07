"""本地中文意图解析器测试。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from bsa.application.memory_scene import MemoryScenePort
from bsa.application.service import SceneEditingService
from bsa.domain.actions import LockAction, MoveAction, PlaceOnAction, UnlockAction
from bsa.domain.errors import DomainError, ErrorCode
from bsa.planner.local_parser import LocalIntentParser
from tests.support import make_object, make_scene


class LocalIntentParserTests(unittest.TestCase):
    """明确指令在本地解析，模糊或额外意图关闭失败。"""

    def setUp(self) -> None:
        self.snapshot = make_scene().read_snapshot()
        self.parser = LocalIntentParser()

    def test_explicit_right_placement_creates_confirmable_plan(self) -> None:
        plan = self.parser.parse("把 Lamp 放到 Desk 右侧", self.snapshot)

        self.assertEqual(plan.source, "local_parser")
        self.assertTrue(plan.requires_confirmation)
        self.assertTrue(plan.scene_fingerprint.startswith("sha256:"))
        self.assertEqual(len(plan.actions), 1)
        action = plan.actions[0]
        self.assertIsInstance(action, PlaceOnAction)
        self.assertEqual(action.object_id, "lamp-id")
        self.assertEqual(action.target_id, "desk-id")
        self.assertEqual(action.region, "right")

    def test_lock_is_only_added_when_instruction_explicitly_requests_it(self) -> None:
        unlocked = self.parser.parse("把 Lamp 放在 Desk 中间", self.snapshot)
        locked = self.parser.parse(
            "把 Lamp 放到 Desk 右侧，并锁定 Desk", self.snapshot
        )

        self.assertFalse(any(isinstance(action, LockAction) for action in unlocked.actions))
        self.assertTrue(any(isinstance(action, LockAction) for action in locked.actions))

    def test_chinese_object_names_are_resolved_exactly(self) -> None:
        scene = MemoryScenePort(
            (
                make_object("桌子-id", "桌子", (0.0, 0.0, 0.5), (4.0, 2.0, 1.0)),
                make_object("台灯-id", "台灯", (0.0, 0.0, 0.5), (0.4, 0.4, 1.0)),
            )
        )

        plan = self.parser.parse("把台灯放到桌子左侧", scene.read_snapshot())
        action = plan.actions[0]
        self.assertIsInstance(action, PlaceOnAction)
        self.assertEqual(action.object_id, "台灯-id")
        self.assertEqual(action.target_id, "桌子-id")
        self.assertEqual(action.region, "left")

    def test_unknown_object_is_rejected(self) -> None:
        with self.assertRaises(DomainError) as raised:
            self.parser.parse("把 Cup 放到 Desk 右侧", self.snapshot)

        self.assertEqual(raised.exception.code, ErrorCode.OBJECT_NOT_FOUND)
        self.assertEqual(raised.exception.details["name"], "Cup")

    def test_vague_instruction_is_rejected(self) -> None:
        with self.assertRaises(DomainError) as raised:
            self.parser.parse("帮我把桌面布置得更好看", self.snapshot)

        self.assertEqual(raised.exception.code, ErrorCode.ACTION_NOT_SUPPORTED)

    def test_unimplemented_extra_requirement_is_rejected(self) -> None:
        with self.assertRaises(DomainError) as raised:
            self.parser.parse(
                "把 Lamp 放到 Desk 右侧，靠后一点", self.snapshot
            )

        self.assertEqual(raised.exception.code, ErrorCode.ACTION_NOT_SUPPORTED)

    def test_source_and_target_must_be_different(self) -> None:
        with self.assertRaises(DomainError) as raised:
            self.parser.parse("把 Desk 放到 Desk 右侧", self.snapshot)

        self.assertEqual(raised.exception.code, ErrorCode.PRECONDITION_FAILED)

    def test_move_centimeters_creates_verified_world_delta(self) -> None:
        scene = make_scene()
        before = scene.read_snapshot().object_map()["lamp-id"].location_world

        plan = self.parser.parse("Lamp 向右移动 20 厘米", scene.read_snapshot())

        action = plan.actions[0]
        self.assertIsInstance(action, MoveAction)
        self.assertEqual(action.object_id, "lamp-id")
        self.assertEqual(action.delta, (0.2, 0.0, 0.0))
        result = SceneEditingService(scene).execute_plan(plan, confirmed=True)
        self.assertEqual(result.status, "COMMITTED")
        self.assertTrue(result.verification and result.verification.passed)
        after = scene.read_snapshot().object_map()["lamp-id"].location_world
        self.assertAlmostEqual(after[0] - before[0], 0.2)

    def test_move_distance_respects_blender_scene_unit_scale(self) -> None:
        centimeter_units = replace(self.snapshot, unit_scale=0.01)

        plan = self.parser.parse("把 Lamp 向前移动 20厘米", centimeter_units)

        action = plan.actions[0]
        self.assertIsInstance(action, MoveAction)
        self.assertEqual(action.delta, (0.0, -20.0, 0.0))

    def test_explicit_lock_and_unlock_create_whitelisted_actions(self) -> None:
        lock_plan = self.parser.parse("锁定 Desk", self.snapshot)
        self.assertIsInstance(lock_plan.actions[0], LockAction)

        locked_scene = MemoryScenePort(
            (
                make_object(
                    "desk-id",
                    "Desk",
                    (0.0, 0.0, 0.5),
                    (4.0, 2.0, 1.0),
                    locked=True,
                ),
            )
        )
        unlock_plan = self.parser.parse("解除锁定 Desk", locked_scene.read_snapshot())
        self.assertIsInstance(unlock_plan.actions[0], UnlockAction)

    def test_move_locked_object_is_rejected_before_preview(self) -> None:
        locked_scene = MemoryScenePort(
            (
                make_object(
                    "lamp-id",
                    "Lamp",
                    (0.0, 0.0, 0.5),
                    (0.4, 0.4, 1.0),
                    locked=True,
                ),
            )
        )

        with self.assertRaises(DomainError) as raised:
            self.parser.parse("Lamp 向左移动 10厘米", locked_scene.read_snapshot())

        self.assertEqual(raised.exception.code, ErrorCode.OBJECT_LOCKED)

    def test_zero_distance_and_unsupported_unit_are_rejected(self) -> None:
        with self.assertRaises(DomainError) as zero_distance:
            self.parser.parse("Lamp 向右移动 0厘米", self.snapshot)
        self.assertEqual(zero_distance.exception.code, ErrorCode.PRECONDITION_FAILED)

        with self.assertRaises(DomainError) as unsupported_unit:
            self.parser.parse("Lamp 向右移动 20英寸", self.snapshot)
        self.assertEqual(unsupported_unit.exception.code, ErrorCode.ACTION_NOT_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
