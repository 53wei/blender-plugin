"""矩形转接板 P0 的确定性生成和保孔位修改。"""

from __future__ import annotations

import json
import math
import unittest
from dataclasses import replace

from bsa.core.adapter_plate import design_adapter_plate, resize_adapter_plate
from bsa.domain.adapter_plate import (
    AdapterPlateResizePatch,
    AdapterPlateSpec,
    MountingPatternSpec,
    PatternHoleSpec,
)
from bsa.domain.errors import DomainError, ErrorCode


def make_plate() -> AdapterPlateSpec:
    return AdapterPlateSpec(
        plate_id="adapter-demo",
        width_mm=80.0,
        depth_mm=40.0,
        thickness_mm=3.0,
        corner_radius_mm=2.0,
        mounting_patterns=(
            MountingPatternSpec(
                pattern_id="device",
                origin_x_mm=20.0,
                origin_y_mm=20.0,
                holes=(
                    PatternHoleSpec("device-left", -10.0, 0.0, 3.2),
                    PatternHoleSpec("device-right", 10.0, 0.0, 3.2),
                ),
            ),
            MountingPatternSpec(
                pattern_id="support",
                origin_x_mm=40.0,
                origin_y_mm=20.0,
                holes=(
                    PatternHoleSpec("support-front", 0.0, -10.0, 4.2),
                    PatternHoleSpec("support-back", 0.0, 10.0, 4.2),
                ),
            ),
        ),
    )


def world_holes(design: object) -> dict[str, tuple[float, float]]:
    return {
        hole.hole_id: (
            hole.center_mm[0] + design.origin_offset_mm[0],
            hole.center_mm[1] + design.origin_offset_mm[1],
        )
        for hole in design.holes
    }


class AdapterPlateTests(unittest.TestCase):
    def test_design_flattens_patterns_into_stable_holes(self) -> None:
        design = design_adapter_plate(make_plate())
        self.assertEqual(design.size_mm, (80.0, 40.0, 3.0))
        self.assertEqual(design.origin_offset_mm, (0.0, 0.0, 0.0))
        self.assertEqual(
            [(hole.hole_id, hole.pattern_id, hole.center_mm) for hole in design.holes],
            [
                ("device-left", "device", (10.0, 20.0)),
                ("device-right", "device", (30.0, 20.0)),
                ("support-front", "support", (40.0, 10.0)),
                ("support-back", "support", (40.0, 30.0)),
            ],
        )

    def test_same_input_is_deterministic_and_json_compatible(self) -> None:
        first = design_adapter_plate(make_plate())
        second = design_adapter_plate(make_plate())
        self.assertEqual(first, second)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertIsInstance(first.to_dict()["holes"], list)

    def test_invalid_numbers_duplicate_ids_and_outside_holes_fail_closed(self) -> None:
        invalid_specs = (
            replace(make_plate(), width_mm=0.0),
            replace(make_plate(), width_mm=math.inf),
            replace(make_plate(), width_mm=math.nan),
            replace(make_plate(), plate_id=" adapter-demo"),
            replace(
                make_plate(),
                mounting_patterns=(
                    make_plate().mounting_patterns[0],
                    replace(make_plate().mounting_patterns[1], pattern_id="device"),
                ),
            ),
            replace(
                make_plate(),
                mounting_patterns=(
                    MountingPatternSpec(
                        "outside",
                        79.0,
                        20.0,
                        (PatternHoleSpec("outside-hole", 0.0, 0.0, 4.0),),
                    ),
                ),
            ),
        )
        for spec in invalid_specs:
            with self.subTest(spec=spec), self.assertRaises(DomainError) as raised:
                design_adapter_plate(spec)
            self.assertEqual(raised.exception.code, ErrorCode.PRINT_SPEC_INVALID)

    def test_overlapping_holes_and_holes_in_rounded_corner_are_rejected(self) -> None:
        overlapping = replace(
            make_plate(),
            mounting_patterns=(
                MountingPatternSpec(
                    "overlap",
                    20.0,
                    20.0,
                    (
                        PatternHoleSpec("a", 0.0, 0.0, 6.0),
                        PatternHoleSpec("b", 2.0, 0.0, 6.0),
                    ),
                ),
            ),
        )
        rounded_corner = replace(
            make_plate(),
            corner_radius_mm=8.0,
            mounting_patterns=(
                MountingPatternSpec(
                    "corner",
                    2.0,
                    2.0,
                    (PatternHoleSpec("corner-hole", 0.0, 0.0, 2.0),),
                ),
            ),
        )
        for spec in (overlapping, rounded_corner):
            with self.subTest(spec=spec), self.assertRaises(DomainError) as raised:
                design_adapter_plate(spec)
            self.assertEqual(raised.exception.code, ErrorCode.PRINT_SPEC_INVALID)

    def test_resize_from_left_keeps_local_and_world_hole_centers(self) -> None:
        before = design_adapter_plate(make_plate())
        revision = resize_adapter_plate(
            make_plate(),
            AdapterPlateResizePatch(
                new_width_mm=90.0,
                new_depth_mm=None,
                fixed_x_edge="left",
                fixed_y_edge="front",
                preserve_pattern_ids=("device", "support"),
            ),
        )
        self.assertEqual(revision.design.size_mm, (90.0, 40.0, 3.0))
        self.assertEqual(revision.origin_shift_mm, (0.0, 0.0, 0.0))
        self.assertNotIn("-0.0", json.dumps(revision.to_dict()))
        self.assertEqual(world_holes(revision.design), world_holes(before))

    def test_resize_from_right_and_back_moves_plate_but_preserves_world_holes(self) -> None:
        before = design_adapter_plate(make_plate())
        revision = resize_adapter_plate(
            make_plate(),
            AdapterPlateResizePatch(
                new_width_mm=90.0,
                new_depth_mm=50.0,
                fixed_x_edge="right",
                fixed_y_edge="back",
                preserve_pattern_ids=("device", "support"),
            ),
        )
        self.assertEqual(revision.origin_shift_mm, (-10.0, -10.0, 0.0))
        self.assertEqual(world_holes(revision.design), world_holes(before))
        self.assertEqual(revision.updated_spec.mounting_patterns[0].origin_x_mm, 30.0)
        self.assertEqual(revision.updated_spec.mounting_patterns[0].origin_y_mm, 30.0)

    def test_center_resize_moves_each_axis_by_half_delta(self) -> None:
        revision = resize_adapter_plate(
            make_plate(),
            AdapterPlateResizePatch(
                new_width_mm=100.0,
                new_depth_mm=50.0,
                fixed_x_edge="center",
                fixed_y_edge="center",
                preserve_pattern_ids=("device", "support"),
            ),
        )
        self.assertEqual(revision.origin_shift_mm, (-10.0, -5.0, 0.0))
        self.assertEqual(
            revision.updated_spec.mounting_patterns[0].origin_x_mm,
            30.0,
        )

    def test_shrink_that_exposes_a_hole_is_rejected_without_clamping(self) -> None:
        with self.assertRaises(DomainError) as raised:
            resize_adapter_plate(
                make_plate(),
                AdapterPlateResizePatch(
                    new_width_mm=30.0,
                    new_depth_mm=None,
                    fixed_x_edge="left",
                    fixed_y_edge="front",
                    preserve_pattern_ids=("device", "support"),
                ),
            )
        self.assertEqual(raised.exception.code, ErrorCode.PRINT_SPEC_INVALID)

    def test_partial_pattern_preservation_is_explicitly_unsupported(self) -> None:
        with self.assertRaises(DomainError) as raised:
            resize_adapter_plate(
                make_plate(),
                AdapterPlateResizePatch(
                    new_width_mm=90.0,
                    new_depth_mm=None,
                    fixed_x_edge="left",
                    fixed_y_edge="front",
                    preserve_pattern_ids=("device",),
                ),
            )
        self.assertEqual(
            raised.exception.code,
            ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
        )


if __name__ == "__main__":
    unittest.main()
