"""Deterministic camera framing and stale-preview tests."""

from __future__ import annotations

import unittest

from bsa.core.camera_framing import (
    CameraFramePlan,
    bounds_for_objects,
    build_camera_frame_plan,
    describe_camera_plan,
    validate_camera_plan_current,
)
from bsa.domain.errors import DomainError, ErrorCode
from tests.support import make_scene


class CameraFramingTests(unittest.TestCase):
    def test_union_bounds_include_every_selected_object(self) -> None:
        snapshot = make_scene().read_snapshot()
        bounds = bounds_for_objects(snapshot, ("desk-id", "chair-id"))
        self.assertEqual(bounds.min_xyz[0], -2.0)
        self.assertEqual(bounds.max_xyz[0], 4.5)

    def test_plan_round_trip_preserves_json_vectors(self) -> None:
        snapshot = make_scene().read_snapshot()
        plan = build_camera_frame_plan(
            snapshot, ("desk-id", "lamp-id"), lens_mm=50.0, aspect_ratio=16 / 9, margin=0.1
        )
        parsed = CameraFramePlan.from_dict(plan.to_dict())
        self.assertEqual(parsed, plan)
        self.assertIsInstance(plan.to_dict()["camera_location"], list)
        invalid = plan.to_dict()
        invalid["margin"] = 0.9
        with self.assertRaises(DomainError):
            CameraFramePlan.from_dict(invalid)

    def test_larger_margin_moves_camera_farther_away(self) -> None:
        snapshot = make_scene().read_snapshot()
        near = build_camera_frame_plan(
            snapshot, ("desk-id",), lens_mm=50.0, aspect_ratio=1.0, margin=0.0
        )
        far = build_camera_frame_plan(
            snapshot, ("desk-id",), lens_mm=50.0, aspect_ratio=1.0, margin=0.3
        )
        self.assertGreater(far.camera_location[0], near.camera_location[0])

    def test_longer_lens_moves_camera_farther_away(self) -> None:
        snapshot = make_scene().read_snapshot()
        wide = build_camera_frame_plan(
            snapshot, ("desk-id",), lens_mm=24.0, aspect_ratio=1.0, margin=0.1
        )
        tele = build_camera_frame_plan(
            snapshot, ("desk-id",), lens_mm=85.0, aspect_ratio=1.0, margin=0.1
        )
        self.assertGreater(tele.camera_location[0], wide.camera_location[0])

    def test_wide_render_aspect_respects_vertical_field_of_view(self) -> None:
        snapshot = make_scene().read_snapshot()
        square = build_camera_frame_plan(
            snapshot, ("desk-id",), lens_mm=50.0, aspect_ratio=1.0, margin=0.1
        )
        wide = build_camera_frame_plan(
            snapshot, ("desk-id",), lens_mm=50.0, aspect_ratio=2.0, margin=0.1
        )
        self.assertGreater(wide.camera_location[0], square.camera_location[0])

    def test_invalid_camera_inputs_fail_before_blender_changes(self) -> None:
        snapshot = make_scene().read_snapshot()
        for lens, aspect, margin in ((5.0, 1.0, 0.1), (50.0, 0.0, 0.1), (50.0, 1.0, 0.8)):
            with self.subTest(lens=lens, aspect=aspect, margin=margin):
                with self.assertRaises(DomainError) as raised:
                    build_camera_frame_plan(
                        snapshot,
                        ("desk-id",),
                        lens_mm=lens,
                        aspect_ratio=aspect,
                        margin=margin,
                    )
                self.assertEqual(raised.exception.code, ErrorCode.PRECONDITION_FAILED)
        with self.assertRaises(DomainError):
            build_camera_frame_plan(
                snapshot,
                ("desk-id",),
                lens_mm=50.0,
                aspect_ratio=1.0,
                margin=0.1,
                view_direction=(0.0, 0.0, 0.0),
            )

    def test_camera_preview_becomes_stale_after_object_move(self) -> None:
        scene = make_scene()
        plan = build_camera_frame_plan(
            scene.read_snapshot(), ("desk-id",), lens_mm=50.0, aspect_ratio=1.0, margin=0.1
        )
        scene.apply_location("desk-id", (1.0, 0.0, 0.5))
        with self.assertRaises(DomainError) as raised:
            validate_camera_plan_current(plan, scene.read_snapshot())
        self.assertEqual(raised.exception.code, ErrorCode.PLAN_STALE)

    def test_camera_preview_names_objects_and_confirmation_boundary(self) -> None:
        snapshot = make_scene().read_snapshot()
        plan = build_camera_frame_plan(
            snapshot, ("desk-id", "lamp-id"), lens_mm=35.0, aspect_ratio=1.0, margin=0.2
        )
        preview = describe_camera_plan(plan, snapshot)
        self.assertIn("Desk", preview)
        self.assertIn("Lamp", preview)
        self.assertIn("确认后", preview)


if __name__ == "__main__":
    unittest.main()
