"""转接板真实网格规格构造与独立回读验证。"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping

from .adapter_plate import design_adapter_plate
from ..domain.adapter_plate import (
    AdapterPlateDesign,
    AdapterPlateHole,
    AdapterPlateSpec,
    MountingPatternSpec,
    PatternHoleSpec,
)
from ..domain.adapter_plate_mesh import (
    AdapterPlateMeshSpec,
    AdapterPlateMeshState,
)
from ..domain.errors import DomainError, ErrorCode
from ..domain.results import CheckResult, VerificationResult

_TOLERANCE_MM = 0.02
_OUTER_CORNER_SEGMENTS = 8
_HOLE_SEGMENTS = 32


def _payload_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            f"{field} 必须是有限数值",
            {"field": field},
        )
    parsed = float(value)
    if not math.isfinite(parsed):
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            f"{field} 必须是有限数值",
            {"field": field},
        )
    return parsed


def _payload_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            f"{field} 必须是非空字符串",
            {"field": field},
        )
    return value


def adapter_plate_design_from_dict(payload: Mapping[str, Any]) -> AdapterPlateDesign:
    """严格恢复插件保存的设计元数据，并重新执行本地几何验证。"""

    fields = {
        "schema_version",
        "plate_id",
        "size_mm",
        "corner_radius_mm",
        "origin_offset_mm",
        "holes",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            "转接板设计元数据字段无效",
        )
    size = payload["size_mm"]
    origin = payload["origin_offset_mm"]
    holes = payload["holes"]
    if (
        not isinstance(size, list)
        or len(size) != 3
        or not isinstance(origin, list)
        or len(origin) != 3
        or not isinstance(holes, list)
        or len(holes) > 20
    ):
        raise DomainError(ErrorCode.PRINT_SPEC_INVALID, "转接板设计元数据结构无效")
    parsed_holes: list[AdapterPlateHole] = []
    for index, raw in enumerate(holes):
        hole_fields = {"hole_id", "pattern_id", "center_mm", "diameter_mm"}
        if not isinstance(raw, Mapping) or set(raw) != hole_fields:
            raise DomainError(
                ErrorCode.PRINT_SPEC_INVALID,
                "转接板孔元数据字段无效",
                {"index": index},
            )
        center = raw["center_mm"]
        if not isinstance(center, list) or len(center) != 2:
            raise DomainError(
                ErrorCode.PRINT_SPEC_INVALID,
                "转接板孔中心元数据无效",
                {"index": index},
            )
        parsed_holes.append(
            AdapterPlateHole(
                hole_id=_payload_string(raw["hole_id"], f"holes[{index}].hole_id"),
                pattern_id=_payload_string(
                    raw["pattern_id"],
                    f"holes[{index}].pattern_id",
                ),
                center_mm=(
                    _payload_number(center[0], f"holes[{index}].center_mm[0]"),
                    _payload_number(center[1], f"holes[{index}].center_mm[1]"),
                ),
                diameter_mm=_payload_number(
                    raw["diameter_mm"],
                    f"holes[{index}].diameter_mm",
                ),
            )
        )
    design = AdapterPlateDesign(
        schema_version=_payload_string(payload["schema_version"], "schema_version"),
        plate_id=_payload_string(payload["plate_id"], "plate_id"),
        size_mm=tuple(
            _payload_number(value, f"size_mm[{index}]")
            for index, value in enumerate(size)
        ),  # type: ignore[arg-type]
        corner_radius_mm=_payload_number(
            payload["corner_radius_mm"],
            "corner_radius_mm",
        ),
        origin_offset_mm=tuple(
            _payload_number(value, f"origin_offset_mm[{index}]")
            for index, value in enumerate(origin)
        ),  # type: ignore[arg-type]
        holes=tuple(parsed_holes),
    )
    return _canonical_design(design)


def adapter_plate_spec_from_design(design: AdapterPlateDesign) -> AdapterPlateSpec:
    """把展开孔设计无损还原成可继续修改的参数规格。"""

    validated = _canonical_design(design)
    grouped: dict[str, list[AdapterPlateHole]] = defaultdict(list)
    pattern_order: list[str] = []
    for hole in validated.holes:
        if hole.pattern_id not in grouped:
            pattern_order.append(hole.pattern_id)
        grouped[hole.pattern_id].append(hole)
    return AdapterPlateSpec(
        plate_id=validated.plate_id,
        width_mm=validated.size_mm[0],
        depth_mm=validated.size_mm[1],
        thickness_mm=validated.size_mm[2],
        corner_radius_mm=validated.corner_radius_mm,
        mounting_patterns=tuple(
            MountingPatternSpec(
                pattern_id=pattern_id,
                origin_x_mm=0.0,
                origin_y_mm=0.0,
                holes=tuple(
                    PatternHoleSpec(
                        hole_id=hole.hole_id,
                        offset_x_mm=hole.center_mm[0],
                        offset_y_mm=hole.center_mm[1],
                        diameter_mm=hole.diameter_mm,
                    )
                    for hole in grouped[pattern_id]
                ),
            )
            for pattern_id in pattern_order
        ),
    )


def _canonical_design(design: AdapterPlateDesign) -> AdapterPlateDesign:
    if not isinstance(design, AdapterPlateDesign):
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "design 必须是已验证的转接板规格",
        )
    if design.schema_version != "0.1":
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            "不支持的转接板规格版本",
            {"schema_version": design.schema_version},
        )
    if len(design.size_mm) != 3 or len(design.origin_offset_mm) != 3:
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            "转接板尺寸和原点必须各包含三个坐标",
        )
    grouped: dict[str, list[AdapterPlateHole]] = defaultdict(list)
    pattern_order: list[str] = []
    for hole in design.holes:
        if not isinstance(hole, AdapterPlateHole):
            raise DomainError(
                ErrorCode.PRINT_SPEC_INVALID,
                "转接板孔必须是严格类型",
            )
        if hole.pattern_id not in grouped:
            pattern_order.append(hole.pattern_id)
        grouped[hole.pattern_id].append(hole)
    patterns = tuple(
        MountingPatternSpec(
            pattern_id=pattern_id,
            origin_x_mm=0.0,
            origin_y_mm=0.0,
            holes=tuple(
                PatternHoleSpec(
                    hole_id=hole.hole_id,
                    offset_x_mm=hole.center_mm[0],
                    offset_y_mm=hole.center_mm[1],
                    diameter_mm=hole.diameter_mm,
                )
                for hole in grouped[pattern_id]
            ),
        )
        for pattern_id in pattern_order
    )
    spec = AdapterPlateSpec(
        plate_id=design.plate_id,
        width_mm=design.size_mm[0],
        depth_mm=design.size_mm[1],
        thickness_mm=design.size_mm[2],
        corner_radius_mm=design.corner_radius_mm,
        mounting_patterns=patterns,
    )
    canonical = design_adapter_plate(spec, origin_offset_mm=design.origin_offset_mm)
    expected = {hole.hole_id: hole for hole in design.holes}
    actual = {hole.hole_id: hole for hole in canonical.holes}
    if expected != actual or len(expected) != len(design.holes):
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            "转接板孔规格无法通过本地重建验证",
        )
    return design


def build_adapter_plate_mesh_spec(
    design: AdapterPlateDesign,
) -> AdapterPlateMeshSpec:
    """从已验证设计生成唯一的 P1 网格输入。"""
    validated = _canonical_design(design)
    return AdapterPlateMeshSpec(
        schema_version="0.1",
        plate_id=validated.plate_id,
        size_mm=validated.size_mm,
        corner_radius_mm=validated.corner_radius_mm,
        origin_offset_mm=validated.origin_offset_mm,
        holes=validated.holes,
        outer_corner_segments=_OUTER_CORNER_SEGMENTS,
        hole_segments=_HOLE_SEGMENTS,
    )


def _vector_close(left: tuple[float, ...], right: tuple[float, ...]) -> bool:
    return len(left) == len(right) and all(
        abs(first - second) <= _TOLERANCE_MM
        for first, second in zip(left, right, strict=True)
    )


def _holes_match(
    expected: tuple[AdapterPlateHole, ...],
    actual: tuple[object, ...],
) -> bool:
    if len(expected) != len(actual):
        return False
    remaining = list(actual)
    for planned in expected:
        compatible = [
            (index, measured)
            for index, measured in enumerate(remaining)
            if hasattr(measured, "center_mm") and hasattr(measured, "diameter_mm")
        ]
        if not compatible:
            return False
        index, measured = min(
            compatible,
            key=lambda item: (
                (item[1].center_mm[0] - planned.center_mm[0]) ** 2
                + (item[1].center_mm[1] - planned.center_mm[1]) ** 2
            ),
        )
        if not _vector_close(measured.center_mm, planned.center_mm) or abs(
            measured.diameter_mm - planned.diameter_mm
        ) > _TOLERANCE_MM:
            return False
        remaining.pop(index)
    return not remaining


def verify_adapter_plate_mesh(
    expected: AdapterPlateMeshSpec,
    actual: tuple[AdapterPlateMeshState, ...],
    *,
    plate_id: str,
    transaction_id: str,
    existing_scene_unchanged: bool,
) -> VerificationResult:
    """从实际网格状态验证单一板体、尺寸、孔和既有场景。"""
    state = actual[0] if len(actual) == 1 else None
    checks: list[CheckResult] = [
        CheckResult(
            check_type="adapter_plate_object_set",
            object_ids=tuple(item.object_name for item in actual),
            expected=1,
            actual=len(actual),
            tolerance=None,
            passed=len(actual) == 1,
        )
    ]
    metadata_ok = bool(
        state
        and state.plate_id == plate_id
        and state.transaction_id == transaction_id
    )
    checks.append(
        CheckResult(
            check_type="adapter_plate_metadata",
            object_ids=(state.object_name,) if state else (),
            expected={"plate_id": plate_id, "transaction_id": transaction_id},
            actual=(
                {
                    "plate_id": state.plate_id,
                    "transaction_id": state.transaction_id,
                }
                if state
                else None
            ),
            tolerance=None,
            passed=metadata_ok,
        )
    )
    dimensions_ok = bool(
        state
        and _vector_close(state.size_mm, expected.size_mm)
        and _vector_close(state.origin_offset_mm, expected.origin_offset_mm)
        and abs(state.corner_radius_mm - expected.corner_radius_mm)
        <= _TOLERANCE_MM
    )
    checks.append(
        CheckResult(
            check_type="adapter_plate_dimensions",
            object_ids=(state.object_name,) if state else (),
            expected={
                "size_mm": list(expected.size_mm),
                "origin_offset_mm": list(expected.origin_offset_mm),
                "corner_radius_mm": expected.corner_radius_mm,
            },
            actual=(
                {
                    "size_mm": list(state.size_mm),
                    "origin_offset_mm": list(state.origin_offset_mm),
                    "corner_radius_mm": state.corner_radius_mm,
                }
                if state
                else None
            ),
            tolerance=_TOLERANCE_MM,
            passed=dimensions_ok,
        )
    )
    mesh_ok = bool(
        state
        and state.is_manifold
        and state.connected_components == 1
        and state.vertex_count > 0
        and state.face_count > 0
    )
    checks.append(
        CheckResult(
            check_type="closed_manifold_mesh",
            object_ids=(state.object_name,) if state else (),
            expected={"is_manifold": True, "connected_components": 1},
            actual=(
                {
                    "is_manifold": state.is_manifold,
                    "connected_components": state.connected_components,
                    "vertex_count": state.vertex_count,
                    "face_count": state.face_count,
                }
                if state
                else None
            ),
            tolerance=None,
            passed=mesh_ok,
        )
    )
    holes_ok = bool(
        state
        and state.through_hole_count == len(expected.holes)
        and _holes_match(expected.holes, state.measured_holes)
    )
    checks.append(
        CheckResult(
            check_type="through_hole_geometry",
            object_ids=(state.object_name,) if state else (),
            expected={
                "count": len(expected.holes),
                "holes": [
                    {
                        "center_mm": list(hole.center_mm),
                        "diameter_mm": hole.diameter_mm,
                    }
                    for hole in expected.holes
                ],
            },
            actual=(
                {
                    "count": state.through_hole_count,
                    "holes": [hole.to_dict() for hole in state.measured_holes],
                }
                if state
                else None
            ),
            tolerance=_TOLERANCE_MM,
            passed=holes_ok,
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
            "转接板真实网格创建并验证通过"
            if passed
            else "转接板网格与计划不一致，必须回滚"
        ),
    )
