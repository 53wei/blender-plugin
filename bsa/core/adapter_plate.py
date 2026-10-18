"""矩形转接板的确定性参数推导与保孔位修改。"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable

from ..domain.adapter_plate import (
    AdapterPlateDesign,
    AdapterPlateHole,
    AdapterPlateResizePatch,
    AdapterPlateRevision,
    AdapterPlateSpec,
    MountingPatternSpec,
)
from ..domain.errors import DomainError, ErrorCode


_SUPPORTED_X_EDGES = frozenset({"left", "center", "right"})
_SUPPORTED_Y_EDGES = frozenset({"front", "center", "back"})


def _fail(message: str, **details: object) -> None:
    raise DomainError(ErrorCode.PRINT_SPEC_INVALID, message, dict(details))


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} 不能为空", field=field)
    if value != value.strip():
        _fail(f"{field} 不能包含首尾空白", field=field)
    return value


def _number(
    value: object,
    field: str,
    *,
    allow_zero: bool = False,
    signed: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{field} 必须是有限数值", field=field)
    parsed = float(value)
    if not math.isfinite(parsed):
        _fail(f"{field} 必须是有限数值", field=field)
    if not signed:
        valid = parsed >= 0.0 if allow_zero else parsed > 0.0
        if not valid:
            _fail(
                f"{field} 必须是{'非负' if allow_zero else '正'}有限数值",
                field=field,
                value=parsed,
            )
    return parsed


def _unique(values: Iterable[str], field: str) -> None:
    items = tuple(values)
    if len(items) != len(set(items)):
        _fail(f"{field} 不能重复", field=field)


def _inside_rounded_plate(
    x: float,
    y: float,
    hole_radius: float,
    width: float,
    depth: float,
    corner_radius: float,
) -> bool:
    if (
        x - hole_radius < 0.0
        or x + hole_radius > width
        or y - hole_radius < 0.0
        or y + hole_radius > depth
    ):
        return False
    if corner_radius == 0.0:
        return True

    corner_x = None
    corner_y = None
    if x < corner_radius:
        corner_x = corner_radius
    elif x > width - corner_radius:
        corner_x = width - corner_radius
    if y < corner_radius:
        corner_y = corner_radius
    elif y > depth - corner_radius:
        corner_y = depth - corner_radius
    if corner_x is None or corner_y is None:
        return True
    usable_radius = corner_radius - hole_radius
    if usable_radius < 0.0:
        return False
    return math.hypot(x - corner_x, y - corner_y) <= usable_radius


def design_adapter_plate(
    spec: AdapterPlateSpec,
    *,
    origin_offset_mm: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> AdapterPlateDesign:
    """把安装模式展开为稳定板件规格；不修改 Blender。"""
    plate_id = _identifier(spec.plate_id, "plate_id")
    width = _number(spec.width_mm, "width_mm")
    depth = _number(spec.depth_mm, "depth_mm")
    thickness = _number(spec.thickness_mm, "thickness_mm")
    corner_radius = _number(spec.corner_radius_mm, "corner_radius_mm", allow_zero=True)
    if corner_radius * 2.0 > min(width, depth):
        _fail(
            "圆角半径超过板尺寸允许范围",
            corner_radius_mm=corner_radius,
        )

    if len(origin_offset_mm) != 3:
        _fail("origin_offset_mm 必须包含三个坐标", field="origin_offset_mm")
    origin_offset = tuple(
        _number(value, f"origin_offset_mm[{index}]", signed=True)
        for index, value in enumerate(origin_offset_mm)
    )
    _unique((pattern.pattern_id for pattern in spec.mounting_patterns), "安装模式 ID")
    holes: list[AdapterPlateHole] = []
    all_hole_ids: list[str] = []
    for pattern in spec.mounting_patterns:
        pattern_id = _identifier(pattern.pattern_id, "pattern_id")
        origin_x = _number(
            pattern.origin_x_mm,
            f"pattern.{pattern_id}.origin_x_mm",
            signed=True,
        )
        origin_y = _number(
            pattern.origin_y_mm,
            f"pattern.{pattern_id}.origin_y_mm",
            signed=True,
        )
        _unique((hole.hole_id for hole in pattern.holes), f"{pattern_id} 的孔 ID")
        for hole in pattern.holes:
            hole_id = _identifier(hole.hole_id, "hole_id")
            offset_x = _number(
                hole.offset_x_mm,
                f"hole.{hole_id}.offset_x_mm",
                signed=True,
            )
            offset_y = _number(
                hole.offset_y_mm,
                f"hole.{hole_id}.offset_y_mm",
                signed=True,
            )
            diameter = _number(hole.diameter_mm, f"hole.{hole_id}.diameter_mm")
            center = (origin_x + offset_x, origin_y + offset_y)
            if not _inside_rounded_plate(
                center[0],
                center[1],
                diameter / 2.0,
                width,
                depth,
                corner_radius,
            ):
                _fail(
                    f"孔 {hole_id} 未完整落在板轮廓内",
                    hole_id=hole_id,
                    center_mm=list(center),
                )
            holes.append(
                AdapterPlateHole(
                    hole_id=hole_id,
                    pattern_id=pattern_id,
                    center_mm=center,
                    diameter_mm=diameter,
                )
            )
            all_hole_ids.append(hole_id)
    _unique(all_hole_ids, "全局孔 ID")

    for index, left in enumerate(holes):
        for right in holes[index + 1 :]:
            distance = math.dist(left.center_mm, right.center_mm)
            minimum = (left.diameter_mm + right.diameter_mm) / 2.0
            if distance < minimum:
                _fail(
                    f"孔 {left.hole_id} 与 {right.hole_id} 重叠",
                    hole_ids=[left.hole_id, right.hole_id],
                )

    return AdapterPlateDesign(
        schema_version="0.1",
        plate_id=plate_id,
        size_mm=(width, depth, thickness),
        corner_radius_mm=corner_radius,
        origin_offset_mm=origin_offset,
        holes=tuple(holes),
    )


def _axis_shift(delta: float, fixed_edge: str, axis: str) -> float:
    supported = _SUPPORTED_X_EDGES if axis == "x" else _SUPPORTED_Y_EDGES
    if fixed_edge not in supported:
        _fail(
            f"不支持的 {axis.upper()} 轴固定边",
            axis=axis,
            fixed_edge=fixed_edge,
        )
    zero_edge = "left" if axis == "x" else "front"
    far_edge = "right" if axis == "x" else "back"
    if fixed_edge == zero_edge:
        return 0.0
    if fixed_edge == far_edge:
        return delta
    return delta / 2.0


def resize_adapter_plate(
    spec: AdapterPlateSpec,
    patch: AdapterPlateResizePatch,
) -> AdapterPlateRevision:
    """改变板尺寸，同时以坐标补偿保持全部安装模式世界位置不变。"""
    before = design_adapter_plate(spec)
    if patch.new_width_mm is None and patch.new_depth_mm is None:
        _fail("修改必须提供新宽度或新深度")

    pattern_ids = tuple(pattern.pattern_id for pattern in spec.mounting_patterns)
    if (
        len(patch.preserve_pattern_ids) != len(set(patch.preserve_pattern_ids))
        or set(patch.preserve_pattern_ids) != set(pattern_ids)
    ):
        raise DomainError(
            ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
            "P0 只支持保持全部安装模式的世界位置",
            {
                "required_pattern_ids": list(pattern_ids),
                "provided_pattern_ids": list(patch.preserve_pattern_ids),
            },
        )

    new_width = (
        spec.width_mm
        if patch.new_width_mm is None
        else _number(patch.new_width_mm, "new_width_mm")
    )
    new_depth = (
        spec.depth_mm
        if patch.new_depth_mm is None
        else _number(patch.new_depth_mm, "new_depth_mm")
    )
    x_shift = _axis_shift(new_width - spec.width_mm, patch.fixed_x_edge, "x")
    y_shift = _axis_shift(new_depth - spec.depth_mm, patch.fixed_y_edge, "y")
    updated_patterns = tuple(
        replace(
            pattern,
            origin_x_mm=pattern.origin_x_mm + x_shift,
            origin_y_mm=pattern.origin_y_mm + y_shift,
        )
        for pattern in spec.mounting_patterns
    )
    updated_spec = replace(
        spec,
        width_mm=new_width,
        depth_mm=new_depth,
        mounting_patterns=updated_patterns,
    )
    origin_shift = (
        0.0 if x_shift == 0.0 else -x_shift,
        0.0 if y_shift == 0.0 else -y_shift,
        0.0,
    )
    design = design_adapter_plate(updated_spec, origin_offset_mm=origin_shift)
    return AdapterPlateRevision(
        schema_version="0.1",
        plate_id=spec.plate_id,
        before_size_mm=before.size_mm,
        after_size_mm=design.size_mm,
        origin_shift_mm=origin_shift,
        preserved_pattern_ids=patch.preserve_pattern_ids,
        updated_spec=updated_spec,
        design=design,
    )
