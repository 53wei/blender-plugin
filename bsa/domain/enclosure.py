"""参数化电路板外壳的纯领域数据；全部长度单位均为毫米。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MountingHoleSpec:
    """电路板局部坐标中的圆形安装孔。"""

    hole_id: str
    x_mm: float
    y_mm: float
    diameter_mm: float


@dataclass(frozen=True)
class RectangularPortSpec:
    """位于某一垂直侧壁上的矩形接口。"""

    port_id: str
    side: str
    center_mm: float
    z_from_board_bottom_mm: float
    width_mm: float
    height_mm: float


@dataclass(frozen=True)
class BoardSpec:
    """P0 支持的轴对齐矩形电路板及机械接口。"""

    board_id: str
    width_mm: float
    depth_mm: float
    height_mm: float
    mounting_holes: tuple[MountingHoleSpec, ...] = ()
    ports: tuple[RectangularPortSpec, ...] = ()


@dataclass(frozen=True)
class EnclosureParameters:
    """用户可以调整、但不会偷偷夹值的外壳参数。"""

    wall_thickness_mm: float
    floor_thickness_mm: float
    lid_thickness_mm: float
    board_clearance_xy_mm: float
    top_clearance_mm: float
    boss_height_mm: float
    boss_outer_diameter_mm: float
    screw_hole_diameter_mm: float
    port_clearance_mm: float
    corner_radius_mm: float


@dataclass(frozen=True)
class FdmPrintProfile:
    """P0 检查器使用的最小 FDM 制造约束。"""

    profile_id: str
    nozzle_diameter_mm: float
    minimum_wall_thickness_mm: float
    minimum_hole_diameter_mm: float
    minimum_fit_clearance_mm: float


@dataclass(frozen=True)
class PortCutout:
    """已经加入装配间隙的侧壁开口结果。"""

    port_id: str
    side: str
    center_on_wall_mm: float
    center_z_mm: float
    opening_size_mm: tuple[float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "port_id": self.port_id,
            "side": self.side,
            "center_on_wall_mm": self.center_on_wall_mm,
            "center_z_mm": self.center_z_mm,
            "opening_size_mm": list(self.opening_size_mm),
        }


@dataclass(frozen=True)
class EnclosureDesign:
    """可供后续 Blender executor 消费的确定性几何规格。"""

    schema_version: str
    board_id: str
    inner_size_mm: tuple[float, float, float]
    outer_size_mm: tuple[float, float, float]
    board_origin_mm: tuple[float, float, float]
    board_size_mm: tuple[float, float, float]
    boss_centers_mm: tuple[tuple[float, float, float], ...]
    boss_height_mm: float
    boss_outer_diameter_mm: float
    screw_hole_diameter_mm: float
    wall_thickness_mm: float
    floor_thickness_mm: float
    lid_thickness_mm: float
    board_clearance_xy_mm: float
    top_clearance_mm: float
    corner_radius_mm: float
    port_cutouts: tuple[PortCutout, ...]

    def to_dict(self) -> dict[str, Any]:
        """返回稳定且可 JSON 序列化的 P0 规格。"""
        return {
            "schema_version": self.schema_version,
            "board_id": self.board_id,
            "inner_size_mm": list(self.inner_size_mm),
            "outer_size_mm": list(self.outer_size_mm),
            "board_origin_mm": list(self.board_origin_mm),
            "board_size_mm": list(self.board_size_mm),
            "boss_centers_mm": [list(center) for center in self.boss_centers_mm],
            "boss_height_mm": self.boss_height_mm,
            "boss_outer_diameter_mm": self.boss_outer_diameter_mm,
            "screw_hole_diameter_mm": self.screw_hole_diameter_mm,
            "wall_thickness_mm": self.wall_thickness_mm,
            "floor_thickness_mm": self.floor_thickness_mm,
            "lid_thickness_mm": self.lid_thickness_mm,
            "board_clearance_xy_mm": self.board_clearance_xy_mm,
            "top_clearance_mm": self.top_clearance_mm,
            "corner_radius_mm": self.corner_radius_mm,
            "port_cutouts": [cutout.to_dict() for cutout in self.port_cutouts],
        }


@dataclass(frozen=True)
class EnclosureIssue:
    """用户可读且机器可判定的打印约束问题。"""

    code: str
    severity: str
    field: str
    message: str
    actual_mm: float
    required_minimum_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
            "actual_mm": self.actual_mm,
            "required_minimum_mm": self.required_minimum_mm,
        }
