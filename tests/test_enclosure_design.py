"""参数化电路板外壳 P0 的确定性尺寸与打印规则。"""

from __future__ import annotations

import math
import unittest
from dataclasses import replace

from bsa.core.enclosure import design_enclosure, inspect_enclosure_design
from bsa.domain.enclosure import (
    BoardSpec,
    EnclosureParameters,
    FdmPrintProfile,
    MountingHoleSpec,
    RectangularPortSpec,
)
from bsa.domain.errors import DomainError, ErrorCode


def make_board() -> BoardSpec:
    return BoardSpec(
        board_id="synthetic-demo-board",
        width_mm=70.0,
        depth_mm=50.0,
        height_mm=12.0,
        mounting_holes=(
            MountingHoleSpec("h1", 5.0, 5.0, 3.2),
            MountingHoleSpec("h2", 65.0, 5.0, 3.2),
            MountingHoleSpec("h3", 65.0, 45.0, 3.2),
            MountingHoleSpec("h4", 5.0, 45.0, 3.2),
        ),
        ports=(
            RectangularPortSpec(
                port_id="usb",
                side="front",
                center_mm=35.0,
                z_from_board_bottom_mm=1.0,
                width_mm=12.0,
                height_mm=6.0,
            ),
        ),
    )


def make_parameters() -> EnclosureParameters:
    return EnclosureParameters(
        wall_thickness_mm=2.0,
        floor_thickness_mm=2.0,
        lid_thickness_mm=2.0,
        board_clearance_xy_mm=1.0,
        top_clearance_mm=3.0,
        boss_height_mm=4.0,
        boss_outer_diameter_mm=6.0,
        screw_hole_diameter_mm=2.6,
        port_clearance_mm=0.5,
        corner_radius_mm=2.0,
    )


class EnclosureDesignTests(unittest.TestCase):
    def test_design_derives_exact_dimensions_and_local_positions(self) -> None:
        design = design_enclosure(make_board(), make_parameters())
        self.assertEqual(design.inner_size_mm, (72.0, 52.0, 19.0))
        self.assertEqual(design.outer_size_mm, (76.0, 56.0, 23.0))
        self.assertEqual(design.board_origin_mm, (3.0, 3.0, 6.0))
        self.assertEqual(design.board_size_mm, (70.0, 50.0, 12.0))
        self.assertEqual(design.boss_height_mm, 4.0)
        self.assertEqual(design.top_clearance_mm, 3.0)
        self.assertEqual(design.corner_radius_mm, 2.0)
        self.assertEqual(design.boss_centers_mm[0], (8.0, 8.0, 2.0))
        self.assertEqual(design.port_cutouts[0].opening_size_mm, (13.0, 7.0))

    def test_changing_clearance_moves_shell_and_bosses_without_changing_hole_pattern(self) -> None:
        board = make_board()
        original = design_enclosure(board, make_parameters())
        wider = design_enclosure(
            board, replace(make_parameters(), board_clearance_xy_mm=3.5)
        )
        self.assertEqual(wider.outer_size_mm[0] - original.outer_size_mm[0], 5.0)
        self.assertEqual(wider.outer_size_mm[1] - original.outer_size_mm[1], 5.0)
        original_relative = tuple(
            (x - original.board_origin_mm[0], y - original.board_origin_mm[1])
            for x, y, _z in original.boss_centers_mm
        )
        wider_relative = tuple(
            (x - wider.board_origin_mm[0], y - wider.board_origin_mm[1])
            for x, y, _z in wider.boss_centers_mm
        )
        self.assertEqual(original_relative, wider_relative)

    def test_invalid_numbers_and_mounting_holes_fail_closed(self) -> None:
        for value in (-1.0, 0.0, math.inf, math.nan):
            with self.subTest(value=value):
                with self.assertRaises(DomainError) as raised:
                    design_enclosure(
                        replace(make_board(), width_mm=value), make_parameters()
                    )
                self.assertEqual(raised.exception.code, ErrorCode.PRINT_SPEC_INVALID)

        outside = replace(
            make_board(),
            mounting_holes=(MountingHoleSpec("outside", 70.0, 25.0, 3.2),),
        )
        with self.assertRaises(DomainError) as raised:
            design_enclosure(outside, make_parameters())
        self.assertEqual(raised.exception.code, ErrorCode.PRINT_SPEC_INVALID)

    def test_port_must_fit_supported_side_span_and_height(self) -> None:
        outside = replace(
            make_board(),
            ports=(
                RectangularPortSpec(
                    "bad", "front", 69.0, 10.0, 8.0, 8.0
                ),
            ),
        )
        with self.assertRaises(DomainError) as raised:
            design_enclosure(outside, make_parameters())
        self.assertEqual(raised.exception.code, ErrorCode.PRINT_SPEC_INVALID)
        self.assertIn("接口", raised.exception.message)

    def test_print_profile_reports_blocking_wall_hole_and_clearance_issues(self) -> None:
        design = design_enclosure(
            make_board(),
            replace(
                make_parameters(),
                wall_thickness_mm=0.8,
                screw_hole_diameter_mm=1.8,
                board_clearance_xy_mm=0.15,
            ),
        )
        issues = inspect_enclosure_design(
            design,
            FdmPrintProfile(
                profile_id="synthetic-fdm",
                nozzle_diameter_mm=0.4,
                minimum_wall_thickness_mm=1.2,
                minimum_hole_diameter_mm=2.0,
                minimum_fit_clearance_mm=0.25,
            ),
        )
        self.assertEqual(
            {issue.code for issue in issues},
            {"WALL_TOO_THIN", "HOLE_TOO_SMALL", "CLEARANCE_TOO_SMALL"},
        )
        self.assertTrue(all(issue.severity == "blocking" for issue in issues))

    def test_same_input_is_deterministic_and_json_compatible(self) -> None:
        first = design_enclosure(make_board(), make_parameters())
        second = design_enclosure(make_board(), make_parameters())
        self.assertEqual(first, second)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.to_dict()["schema_version"], "0.1")

    def test_invalid_print_profile_has_its_own_stable_error(self) -> None:
        design = design_enclosure(make_board(), make_parameters())
        with self.assertRaises(DomainError) as raised:
            inspect_enclosure_design(
                design,
                FdmPrintProfile(
                    profile_id="invalid",
                    nozzle_diameter_mm=0.0,
                    minimum_wall_thickness_mm=1.2,
                    minimum_hole_diameter_mm=2.0,
                    minimum_fit_clearance_mm=0.25,
                ),
            )
        self.assertEqual(raised.exception.code, ErrorCode.PRINT_PROFILE_INVALID)

    def test_minimum_wall_rule_also_checks_floor_and_lid(self) -> None:
        design = design_enclosure(
            make_board(),
            replace(
                make_parameters(), floor_thickness_mm=0.9, lid_thickness_mm=1.0
            ),
        )
        issues = inspect_enclosure_design(
            design,
            FdmPrintProfile(
                profile_id="synthetic-fdm",
                nozzle_diameter_mm=0.4,
                minimum_wall_thickness_mm=1.2,
                minimum_hole_diameter_mm=2.0,
                minimum_fit_clearance_mm=0.25,
            ),
        )
        self.assertEqual(
            {issue.field for issue in issues},
            {"floor_thickness_mm", "lid_thickness_mm"},
        )


if __name__ == "__main__":
    unittest.main()
