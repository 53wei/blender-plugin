"""把外壳规格展开成确定性的 Blender 装配预览部件。"""

from __future__ import annotations

import math

from ..domain.enclosure import EnclosureDesign
from ..domain.enclosure_preview import EnclosurePartSpec, EnclosurePartState
from ..domain.errors import DomainError, ErrorCode
from ..domain.results import CheckResult, VerificationResult

_TOLERANCE_MM = 1e-5


def _box(
    part_id: str,
    part_type: str,
    dimensions_mm: tuple[float, float, float],
    center_mm: tuple[float, float, float],
    *,
    display_mode: str = "solid",
) -> EnclosurePartSpec:
    if any(not math.isfinite(value) or value <= 0.0 for value in dimensions_mm):
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            "预览部件尺寸必须是正有限数值",
            {"part_id": part_id, "dimensions_mm": list(dimensions_mm)},
        )
    if any(not math.isfinite(value) for value in center_mm):
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            "预览部件中心必须是有限数值",
            {"part_id": part_id, "center_mm": list(center_mm)},
        )
    return EnclosurePartSpec(
        part_id=part_id,
        part_type=part_type,
        shape="box",
        center_mm=center_mm,
        dimensions_mm=dimensions_mm,
        display_mode=display_mode,
    )


def build_enclosure_preview_parts(
    design: EnclosureDesign,
) -> tuple[EnclosurePartSpec, ...]:
    """生成 P1 装配预览；不修改 Blender，也不声称网格可直接打印。"""
    inner_width, inner_depth, inner_height = design.inner_size_mm
    outer_width, outer_depth, _outer_height = design.outer_size_mm
    wall = design.wall_thickness_mm
    floor = design.floor_thickness_mm
    lid = design.lid_thickness_mm
    wall_center_z = floor + inner_height / 2.0

    parts: list[EnclosurePartSpec] = [
        _box(
            "base_floor",
            "base_floor",
            (outer_width, outer_depth, floor),
            (outer_width / 2.0, outer_depth / 2.0, floor / 2.0),
        ),
        _box(
            "wall_front",
            "wall",
            (inner_width, wall, inner_height),
            (wall + inner_width / 2.0, wall / 2.0, wall_center_z),
        ),
        _box(
            "wall_back",
            "wall",
            (inner_width, wall, inner_height),
            (wall + inner_width / 2.0, outer_depth - wall / 2.0, wall_center_z),
        ),
        _box(
            "wall_left",
            "wall",
            (wall, outer_depth, inner_height),
            (wall / 2.0, outer_depth / 2.0, wall_center_z),
        ),
        _box(
            "wall_right",
            "wall",
            (wall, outer_depth, inner_height),
            (outer_width - wall / 2.0, outer_depth / 2.0, wall_center_z),
        ),
        _box(
            "lid",
            "lid",
            (outer_width, outer_depth, lid),
            (
                outer_width / 2.0,
                outer_depth / 2.0,
                floor + inner_height + lid / 2.0,
            ),
            display_mode="wire",
        ),
    ]

    board_width, board_depth, board_height = design.board_size_mm
    board_x, board_y, board_z = design.board_origin_mm
    parts.append(
        _box(
            "board_proxy",
            "board_proxy",
            design.board_size_mm,
            (
                board_x + board_width / 2.0,
                board_y + board_depth / 2.0,
                board_z + board_height / 2.0,
            ),
            display_mode="wire",
        )
    )

    for index, (x, y, z_bottom) in enumerate(design.boss_centers_mm, start=1):
        cylinder_dimensions = (
            design.boss_outer_diameter_mm,
            design.boss_outer_diameter_mm,
            design.boss_height_mm,
        )
        validated = _box(
            f"boss_{index:03d}",
            "mounting_boss",
            cylinder_dimensions,
            (x, y, z_bottom + design.boss_height_mm / 2.0),
        )
        parts.append(
            EnclosurePartSpec(
                part_id=validated.part_id,
                part_type=validated.part_type,
                shape="cylinder",
                center_mm=validated.center_mm,
                dimensions_mm=validated.dimensions_mm,
                display_mode=validated.display_mode,
            )
        )

    for cutout in design.port_cutouts:
        opening_width, opening_height = cutout.opening_size_mm
        if cutout.side == "front":
            center = (cutout.center_on_wall_mm, wall / 2.0, cutout.center_z_mm)
            dimensions = (opening_width, wall, opening_height)
        elif cutout.side == "back":
            center = (
                cutout.center_on_wall_mm,
                outer_depth - wall / 2.0,
                cutout.center_z_mm,
            )
            dimensions = (opening_width, wall, opening_height)
        elif cutout.side == "left":
            center = (wall / 2.0, cutout.center_on_wall_mm, cutout.center_z_mm)
            dimensions = (wall, opening_width, opening_height)
        elif cutout.side == "right":
            center = (
                outer_width - wall / 2.0,
                cutout.center_on_wall_mm,
                cutout.center_z_mm,
            )
            dimensions = (wall, opening_width, opening_height)
        else:
            raise DomainError(
                ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
                "预览执行器不支持该接口侧面",
                {"port_id": cutout.port_id, "side": cutout.side},
            )
        parts.append(
            _box(
                f"port_{cutout.port_id}",
                "port_cutout_proxy",
                dimensions,
                center,
                display_mode="wire",
            )
        )

    part_ids = [part.part_id for part in parts]
    if len(part_ids) != len(set(part_ids)):
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            "预览部件 ID 发生冲突",
            {"part_ids": part_ids},
        )
    return tuple(parts)


def _vectors_close(
    left: tuple[float, float, float], right: tuple[float, float, float]
) -> bool:
    return all(
        abs(first - second) <= _TOLERANCE_MM
        for first, second in zip(left, right, strict=True)
    )


def verify_enclosure_preview(
    expected: tuple[EnclosurePartSpec, ...],
    actual: tuple[EnclosurePartState, ...],
    *,
    enclosure_id: str,
    transaction_id: str,
    existing_scene_unchanged: bool,
) -> VerificationResult:
    """按部件白名单和毫米尺寸验证执行结果。"""
    expected_by_id = {part.part_id: part for part in expected}
    actual_by_id = {part.part_id: part for part in actual}
    expected_ids = tuple(sorted(expected_by_id))
    actual_ids = tuple(sorted(actual_by_id))
    checks: list[CheckResult] = [
        CheckResult(
            check_type="preview_part_set",
            object_ids=actual_ids,
            expected=expected_ids,
            actual=actual_ids,
            tolerance=None,
            passed=expected_ids == actual_ids and len(actual_by_id) == len(actual),
        )
    ]
    for part_id in expected_ids:
        planned = expected_by_id[part_id]
        created = actual_by_id.get(part_id)
        matches = bool(
            created
            and created.enclosure_id == enclosure_id
            and created.transaction_id == transaction_id
            and created.part_type == planned.part_type
            and created.shape == planned.shape
            and created.display_mode == planned.display_mode
            and _vectors_close(created.center_mm, planned.center_mm)
            and _vectors_close(created.dimensions_mm, planned.dimensions_mm)
        )
        checks.append(
            CheckResult(
                check_type="preview_part_spec",
                object_ids=(part_id,),
                expected=planned.to_dict(),
                actual=(
                    {
                        "part_id": created.part_id,
                        "part_type": created.part_type,
                        "shape": created.shape,
                        "center_mm": list(created.center_mm),
                        "dimensions_mm": list(created.dimensions_mm),
                        "display_mode": created.display_mode,
                    }
                    if created
                    else None
                ),
                tolerance=_TOLERANCE_MM,
                passed=matches,
            )
        )
    checks.append(
        CheckResult(
            check_type="existing_scene_unchanged",
            object_ids=(),
            expected=True,
            actual=existing_scene_unchanged,
            tolerance=None,
            passed=existing_scene_unchanged,
        )
    )
    unauthorized = () if existing_scene_unchanged else ("existing_scene",)
    passed = all(check.passed for check in checks) and not unauthorized
    return VerificationResult(
        passed=passed,
        checks=tuple(checks),
        unauthorized_changes=unauthorized,
        summary=(
            "外壳装配预览创建并验证通过"
            if passed
            else "外壳装配预览与计划不一致，必须回滚"
        ),
    )
