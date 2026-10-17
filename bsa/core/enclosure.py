"""参数化电路板外壳的确定性尺寸推导与 FDM 规则检查。"""

from __future__ import annotations

import math
from collections.abc import Iterable

from ..domain.enclosure import (
    BoardSpec,
    EnclosureDesign,
    EnclosureIssue,
    EnclosureParameters,
    FdmPrintProfile,
    PortCutout,
)
from ..domain.errors import DomainError, ErrorCode


_SUPPORTED_PORT_SIDES = frozenset({"front", "back", "left", "right"})
_MIN_BOSS_RING_MM = 0.8


def _require_identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            f"{field} 不能为空",
            {"field": field},
        )


def _require_number(
    value: float, field: str, *, allow_zero: bool = False
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            f"{field} 必须是有限数值",
            {"field": field},
        )
    parsed = float(value)
    valid_sign = parsed >= 0.0 if allow_zero else parsed > 0.0
    if not math.isfinite(parsed) or not valid_sign:
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            f"{field} 必须是{'非负' if allow_zero else '正'}有限数值",
            {"field": field, "value": parsed},
        )
    return parsed


def _require_unique(values: Iterable[str], field: str) -> None:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            f"{field} 不能重复",
            {"field": field},
        )


def _validate_board(board: BoardSpec, parameters: EnclosureParameters) -> None:
    _require_identifier(board.board_id, "board_id")
    width = _require_number(board.width_mm, "board.width_mm")
    depth = _require_number(board.depth_mm, "board.depth_mm")
    height = _require_number(board.height_mm, "board.height_mm")
    _require_unique((hole.hole_id for hole in board.mounting_holes), "安装孔 ID")
    _require_unique((port.port_id for port in board.ports), "接口 ID")

    for hole in board.mounting_holes:
        _require_identifier(hole.hole_id, "hole_id")
        x = _require_number(hole.x_mm, f"hole.{hole.hole_id}.x_mm", allow_zero=True)
        y = _require_number(hole.y_mm, f"hole.{hole.hole_id}.y_mm", allow_zero=True)
        diameter = _require_number(hole.diameter_mm, f"hole.{hole.hole_id}.diameter_mm")
        radius = diameter / 2.0
        if x - radius < 0.0 or x + radius > width or y - radius < 0.0 or y + radius > depth:
            raise DomainError(
                ErrorCode.PRINT_SPEC_INVALID,
                f"安装孔 {hole.hole_id} 超出电路板边界",
                {"hole_id": hole.hole_id},
            )

    port_clearance = _require_number(
        parameters.port_clearance_mm,
        "parameters.port_clearance_mm",
        allow_zero=True,
    )
    usable_port_height = height + parameters.top_clearance_mm
    for port in board.ports:
        _require_identifier(port.port_id, "port_id")
        if port.side not in _SUPPORTED_PORT_SIDES:
            raise DomainError(
                ErrorCode.PRINT_SPEC_INVALID,
                f"接口 {port.port_id} 的侧面不受支持",
                {"port_id": port.port_id, "side": port.side},
            )
        center = _require_number(
            port.center_mm, f"port.{port.port_id}.center_mm", allow_zero=True
        )
        z_from_board = _require_number(
            port.z_from_board_bottom_mm,
            f"port.{port.port_id}.z_from_board_bottom_mm",
            allow_zero=True,
        )
        port_width = _require_number(port.width_mm, f"port.{port.port_id}.width_mm")
        port_height = _require_number(port.height_mm, f"port.{port.port_id}.height_mm")
        span = width if port.side in {"front", "back"} else depth
        opening_width = port_width + 2.0 * port_clearance
        opening_height = port_height + 2.0 * port_clearance
        if center - opening_width / 2.0 < 0.0 or center + opening_width / 2.0 > span:
            raise DomainError(
                ErrorCode.PRINT_SPEC_INVALID,
                f"接口 {port.port_id} 超出侧壁水平范围",
                {"port_id": port.port_id},
            )
        if (
            z_from_board - port_clearance < 0.0
            or z_from_board + port_height + port_clearance > usable_port_height
        ):
            raise DomainError(
                ErrorCode.PRINT_SPEC_INVALID,
                f"接口 {port.port_id} 超出侧壁高度范围",
                {"port_id": port.port_id, "opening_height_mm": opening_height},
            )


def _validate_parameters(parameters: EnclosureParameters) -> None:
    positive_fields = (
        "wall_thickness_mm",
        "floor_thickness_mm",
        "lid_thickness_mm",
        "board_clearance_xy_mm",
        "boss_height_mm",
        "boss_outer_diameter_mm",
        "screw_hole_diameter_mm",
    )
    for field in positive_fields:
        _require_number(getattr(parameters, field), f"parameters.{field}")
    for field in ("top_clearance_mm", "port_clearance_mm", "corner_radius_mm"):
        _require_number(
            getattr(parameters, field), f"parameters.{field}", allow_zero=True
        )
    ring = (
        parameters.boss_outer_diameter_mm - parameters.screw_hole_diameter_mm
    ) / 2.0
    if ring < _MIN_BOSS_RING_MM:
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            "固定柱孔周围材料不足",
            {"actual_ring_mm": ring, "required_minimum_mm": _MIN_BOSS_RING_MM},
        )


def design_enclosure(
    board: BoardSpec, parameters: EnclosureParameters
) -> EnclosureDesign:
    """从器件和外壳参数生成稳定的 P0 几何规格，不修改 Blender。"""
    _validate_parameters(parameters)
    _validate_board(board, parameters)

    inner_width = board.width_mm + 2.0 * parameters.board_clearance_xy_mm
    inner_depth = board.depth_mm + 2.0 * parameters.board_clearance_xy_mm
    inner_height = parameters.boss_height_mm + board.height_mm + parameters.top_clearance_mm
    outer_width = inner_width + 2.0 * parameters.wall_thickness_mm
    outer_depth = inner_depth + 2.0 * parameters.wall_thickness_mm
    outer_height = (
        parameters.floor_thickness_mm + inner_height + parameters.lid_thickness_mm
    )
    if parameters.corner_radius_mm * 2.0 > min(outer_width, outer_depth):
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            "圆角半径超过外壳尺寸允许范围",
            {"corner_radius_mm": parameters.corner_radius_mm},
        )

    board_origin = (
        parameters.wall_thickness_mm + parameters.board_clearance_xy_mm,
        parameters.wall_thickness_mm + parameters.board_clearance_xy_mm,
        parameters.floor_thickness_mm + parameters.boss_height_mm,
    )
    boss_centers = tuple(
        (
            board_origin[0] + hole.x_mm,
            board_origin[1] + hole.y_mm,
            parameters.floor_thickness_mm,
        )
        for hole in board.mounting_holes
    )
    port_cutouts = tuple(
        PortCutout(
            port_id=port.port_id,
            side=port.side,
            center_on_wall_mm=(
                board_origin[0] + port.center_mm
                if port.side in {"front", "back"}
                else board_origin[1] + port.center_mm
            ),
            center_z_mm=(
                board_origin[2]
                + port.z_from_board_bottom_mm
                + port.height_mm / 2.0
            ),
            opening_size_mm=(
                port.width_mm + 2.0 * parameters.port_clearance_mm,
                port.height_mm + 2.0 * parameters.port_clearance_mm,
            ),
        )
        for port in board.ports
    )
    return EnclosureDesign(
        schema_version="0.1",
        board_id=board.board_id,
        inner_size_mm=(inner_width, inner_depth, inner_height),
        outer_size_mm=(outer_width, outer_depth, outer_height),
        board_origin_mm=board_origin,
        board_size_mm=(board.width_mm, board.depth_mm, board.height_mm),
        boss_centers_mm=boss_centers,
        boss_height_mm=parameters.boss_height_mm,
        boss_outer_diameter_mm=parameters.boss_outer_diameter_mm,
        screw_hole_diameter_mm=parameters.screw_hole_diameter_mm,
        wall_thickness_mm=parameters.wall_thickness_mm,
        floor_thickness_mm=parameters.floor_thickness_mm,
        lid_thickness_mm=parameters.lid_thickness_mm,
        board_clearance_xy_mm=parameters.board_clearance_xy_mm,
        top_clearance_mm=parameters.top_clearance_mm,
        corner_radius_mm=parameters.corner_radius_mm,
        port_cutouts=port_cutouts,
    )


def _validate_profile(profile: FdmPrintProfile) -> None:
    _require_identifier(profile.profile_id, "profile_id")
    for field in (
        "nozzle_diameter_mm",
        "minimum_wall_thickness_mm",
        "minimum_hole_diameter_mm",
        "minimum_fit_clearance_mm",
    ):
        try:
            _require_number(getattr(profile, field), f"profile.{field}")
        except DomainError as error:
            raise DomainError(
                ErrorCode.PRINT_PROFILE_INVALID,
                error.message,
                error.details,
            ) from error


def inspect_enclosure_design(
    design: EnclosureDesign, profile: FdmPrintProfile
) -> tuple[EnclosureIssue, ...]:
    """按显式打印配置检查规格；不修改参数，也不假装完成切片验证。"""
    _validate_profile(profile)
    issues: list[EnclosureIssue] = []
    thickness_fields = (
        ("wall_thickness_mm", design.wall_thickness_mm, "侧壁"),
        ("floor_thickness_mm", design.floor_thickness_mm, "底板"),
        ("lid_thickness_mm", design.lid_thickness_mm, "上盖"),
    )
    for field, actual, label in thickness_fields:
        if actual < profile.minimum_wall_thickness_mm:
            issues.append(
                EnclosureIssue(
                    code="WALL_TOO_THIN",
                    severity="blocking",
                    field=field,
                    message=f"{label}厚度低于当前打印配置的最小值",
                    actual_mm=actual,
                    required_minimum_mm=profile.minimum_wall_thickness_mm,
                )
            )
    if design.screw_hole_diameter_mm < profile.minimum_hole_diameter_mm:
        issues.append(
            EnclosureIssue(
                code="HOLE_TOO_SMALL",
                severity="blocking",
                field="screw_hole_diameter_mm",
                message="螺丝孔直径低于当前打印配置的最小值",
                actual_mm=design.screw_hole_diameter_mm,
                required_minimum_mm=profile.minimum_hole_diameter_mm,
            )
        )
    if design.board_clearance_xy_mm < profile.minimum_fit_clearance_mm:
        issues.append(
            EnclosureIssue(
                code="CLEARANCE_TOO_SMALL",
                severity="blocking",
                field="board_clearance_xy_mm",
                message="电路板侧向间隙低于当前装配配置的最小值",
                actual_mm=design.board_clearance_xy_mm,
                required_minimum_mm=profile.minimum_fit_clearance_mm,
            )
        )
    return tuple(issues)
