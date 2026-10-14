"""Pure tests for the local model-placement workflow."""

from __future__ import annotations

import math
import unittest
from dataclasses import replace

from bsa.application.guided_workflow import GuidedWorkflowPlanBuilder
from bsa.application.memory_scene import MemoryScenePort
from bsa.application.plan_preview import describe_plan
from bsa.application.service import SceneEditingService
from bsa.core.validator import PlanValidator
from bsa.domain.actions import ActionPlan, RotateAction, ScaleUniformAction
from bsa.domain.errors import DomainError, ErrorCode
from tests.support import make_object, make_scene


class GuidedWorkflowTests(unittest.TestCase):
    def test_ground_plan_lands_an_elevated_object(self) -> None:
        scene = MemoryScenePort(
            (make_object("model-id", "Model", (0.0, 0.0, 2.0), (1.0, 1.0, 2.0)),)
        )
        plan = GuidedWorkflowPlanBuilder().ground(scene.read_snapshot(), ("model-id",))
        result = SceneEditingService(scene).execute_plan(plan, confirmed=True)
        self.assertEqual(result.status, "COMMITTED")
        self.assertAlmostEqual(
            scene.read_snapshot().object_map()["model-id"].bbox_world.min_xyz[2],
            0.0,
        )

    def test_ground_plan_rejects_objects_already_on_ground(self) -> None:
        scene = make_scene()
        with self.assertRaises(DomainError) as raised:
            GuidedWorkflowPlanBuilder().ground(scene.read_snapshot(), ("lamp-id",))
        self.assertEqual(raised.exception.code, ErrorCode.PRECONDITION_FAILED)

    def test_alignment_uses_explicit_reference_and_preserves_it(self) -> None:
        scene = make_scene()
        before = scene.read_snapshot().object_map()["desk-id"]
        plan = GuidedWorkflowPlanBuilder().align(
            scene.read_snapshot(),
            ("desk-id", "chair-id"),
            reference_id="desk-id",
            axis="x",
            anchor="center",
        )
        result = SceneEditingService(scene).execute_plan(plan, confirmed=True)
        after = scene.read_snapshot().object_map()
        self.assertEqual(result.status, "COMMITTED")
        self.assertEqual(after["desk-id"].matrix_world, before.matrix_world)
        self.assertAlmostEqual(
            after["chair-id"].bbox_world.center[0],
            after["desk-id"].bbox_world.center[0],
        )

    def test_grid_plan_is_deterministic_and_non_overlapping(self) -> None:
        locations = []
        for _index in range(2):
            scene = make_scene()
            plan = GuidedWorkflowPlanBuilder().grid(
                scene.read_snapshot(),
                ("lamp-id", "desk-id", "chair-id"),
                columns=2,
                gap=0.5,
            )
            result = SceneEditingService(scene).execute_plan(plan, confirmed=True)
            self.assertEqual(result.status, "COMMITTED")
            objects = scene.read_snapshot().object_map()
            locations.append(tuple(objects[key].location_world for key in sorted(objects)))
        self.assertEqual(locations[0], locations[1])

    def test_rotate_plan_executes_and_verifies(self) -> None:
        scene = make_scene()
        plan = GuidedWorkflowPlanBuilder().rotate(
            scene.read_snapshot(),
            ("lamp-id",),
            axis="z",
            angle_degrees=90.0,
        )
        result = SceneEditingService(scene).execute_plan(plan, confirmed=True)
        self.assertEqual(result.status, "COMMITTED")
        self.assertAlmostEqual(
            scene.read_snapshot().object_map()["lamp-id"].rotation_euler[2],
            math.pi / 2.0,
        )

    def test_scale_plan_executes_and_verifies(self) -> None:
        scene = make_scene()
        plan = GuidedWorkflowPlanBuilder().scale(
            scene.read_snapshot(),
            ("lamp-id",),
            factor=1.5,
        )
        result = SceneEditingService(scene).execute_plan(plan, confirmed=True)
        self.assertEqual(result.status, "COMMITTED")
        self.assertEqual(scene.read_snapshot().object_map()["lamp-id"].scale, (1.5, 1.5, 1.5))

    def test_locked_object_transform_is_rejected_before_execution(self) -> None:
        scene = MemoryScenePort(
            (make_object("locked-id", "Locked", (0.0, 0.0, 0.5), (1.0, 1.0, 1.0), locked=True),)
        )
        with self.assertRaises(DomainError) as raised:
            GuidedWorkflowPlanBuilder().scale(
                scene.read_snapshot(),
                ("locked-id",),
                factor=2.0,
            )
        self.assertEqual(raised.exception.code, ErrorCode.OBJECT_LOCKED)

    def test_new_transform_actions_round_trip_through_protocol(self) -> None:
        scene = make_scene()
        rotate = GuidedWorkflowPlanBuilder().rotate(
            scene.read_snapshot(), ("lamp-id",), axis="z", angle_degrees=45.0
        )
        scale = GuidedWorkflowPlanBuilder().scale(
            scene.read_snapshot(), ("lamp-id",), factor=0.5
        )
        parsed_rotate = ActionPlan.from_dict(rotate.to_dict())
        parsed_scale = ActionPlan.from_dict(scale.to_dict())
        self.assertIsInstance(parsed_rotate.actions[0], RotateAction)
        self.assertIsInstance(parsed_scale.actions[0], ScaleUniformAction)
        with self.assertRaises(DomainError) as raised:
            PlanValidator().validate(replace(rotate, source="llm"), scene.read_snapshot())
        self.assertEqual(raised.exception.code, ErrorCode.ACTION_NOT_SUPPORTED)

    def test_preview_names_rotation_and_scale_operations(self) -> None:
        scene = make_scene()
        rotate = GuidedWorkflowPlanBuilder().rotate(
            scene.read_snapshot(), ("lamp-id",), axis="z", angle_degrees=30.0
        )
        scale = GuidedWorkflowPlanBuilder().scale(
            scene.read_snapshot(), ("lamp-id",), factor=2.0
        )
        self.assertIn("旋转 30°", describe_plan(rotate, scene.read_snapshot()))
        self.assertIn("2 倍", describe_plan(scale, scene.read_snapshot()))


if __name__ == "__main__":
    unittest.main()
