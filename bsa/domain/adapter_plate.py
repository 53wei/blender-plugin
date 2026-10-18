"""矩形转接板的纯领域数据；全部长度单位均为毫米。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PatternHoleSpec:
    """相对某一安装模式原点定义的圆形贯穿孔。"""

    hole_id: str
    offset_x_mm: float
    offset_y_mm: float
    diameter_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "hole_id": self.hole_id,
            "offset_x_mm": self.offset_x_mm,
            "offset_y_mm": self.offset_y_mm,
            "diameter_mm": self.diameter_mm,
        }

@dataclass(frozen=True)
class MountingPatternSpec:
    """设备或支架的一组相关安装孔。"""

    pattern_id: str
    origin_x_mm: float
    origin_y_mm: float
    holes: tuple[PatternHoleSpec, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "origin_x_mm": self.origin_x_mm,
            "origin_y_mm": self.origin_y_mm,
            "holes": [hole.to_dict() for hole in self.holes],
        }


@dataclass(frozen=True)
class AdapterPlateSpec:
    """P0 支持的轴对齐矩形转接板输入规格。"""

    plate_id: str
    width_mm: float
    depth_mm: float
    thickness_mm: float
    corner_radius_mm: float
    mounting_patterns: tuple[MountingPatternSpec, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "plate_id": self.plate_id,
            "width_mm": self.width_mm,
            "depth_mm": self.depth_mm,
            "thickness_mm": self.thickness_mm,
            "corner_radius_mm": self.corner_radius_mm,
            "mounting_patterns": [
                pattern.to_dict() for pattern in self.mounting_patterns
            ],
        }


@dataclass(frozen=True)
class AdapterPlateHole:
    """已经展开到板局部坐标的贯穿孔结果。"""

    hole_id: str
    pattern_id: str
    center_mm: tuple[float, float]
    diameter_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "hole_id": self.hole_id,
            "pattern_id": self.pattern_id,
            "center_mm": list(self.center_mm),
            "diameter_mm": self.diameter_mm,
        }


@dataclass(frozen=True)
class AdapterPlateDesign:
    """可由后续 Blender 执行器消费的确定性板件规格。"""

    schema_version: str
    plate_id: str
    size_mm: tuple[float, float, float]
    corner_radius_mm: float
    origin_offset_mm: tuple[float, float, float]
    holes: tuple[AdapterPlateHole, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plate_id": self.plate_id,
            "size_mm": list(self.size_mm),
            "corner_radius_mm": self.corner_radius_mm,
            "origin_offset_mm": list(self.origin_offset_mm),
            "holes": [hole.to_dict() for hole in self.holes],
        }


@dataclass(frozen=True)
class AdapterPlateResizePatch:
    """改变板外形但保留安装模式世界位置的 P0 修改。"""

    new_width_mm: float | None
    new_depth_mm: float | None
    fixed_x_edge: str
    fixed_y_edge: str
    preserve_pattern_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.new_width_mm is not None:
            payload["new_width_mm"] = self.new_width_mm
        if self.new_depth_mm is not None:
            payload["new_depth_mm"] = self.new_depth_mm
        payload.update(
            fixed_x_edge=self.fixed_x_edge,
            fixed_y_edge=self.fixed_y_edge,
            preserve_pattern_ids=list(self.preserve_pattern_ids),
        )
        return payload


@dataclass(frozen=True)
class AdapterPlateRevision:
    """一次已验证修改及其坐标补偿。"""

    schema_version: str
    plate_id: str
    before_size_mm: tuple[float, float, float]
    after_size_mm: tuple[float, float, float]
    origin_shift_mm: tuple[float, float, float]
    preserved_pattern_ids: tuple[str, ...]
    updated_spec: AdapterPlateSpec
    design: AdapterPlateDesign

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plate_id": self.plate_id,
            "before_size_mm": list(self.before_size_mm),
            "after_size_mm": list(self.after_size_mm),
            "origin_shift_mm": list(self.origin_shift_mm),
            "preserved_pattern_ids": list(self.preserved_pattern_ids),
            "updated_spec": self.updated_spec.to_dict(),
            "design": self.design.to_dict(),
        }
