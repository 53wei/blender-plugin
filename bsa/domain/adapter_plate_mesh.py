"""矩形转接板 P1 网格计划、期望规格和回读状态。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adapter_plate import AdapterPlateDesign, AdapterPlateHole

Vector2Mm = tuple[float, float]
Vector3Mm = tuple[float, float, float]


@dataclass(frozen=True)
class MeasuredRoundHole:
    """从实际网格轮廓测得的圆孔，不依赖自定义孔 ID。"""

    center_mm: Vector2Mm
    diameter_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "center_mm": list(self.center_mm),
            "diameter_mm": self.diameter_mm,
        }


@dataclass(frozen=True)
class AdapterPlateMeshSpec:
    """Blender 执行器唯一允许消费的转接板网格规格。"""

    schema_version: str
    plate_id: str
    size_mm: Vector3Mm
    corner_radius_mm: float
    origin_offset_mm: Vector3Mm
    holes: tuple[AdapterPlateHole, ...]
    outer_corner_segments: int
    hole_segments: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plate_id": self.plate_id,
            "size_mm": list(self.size_mm),
            "corner_radius_mm": self.corner_radius_mm,
            "origin_offset_mm": list(self.origin_offset_mm),
            "holes": [hole.to_dict() for hole in self.holes],
            "outer_corner_segments": self.outer_corner_segments,
            "hole_segments": self.hole_segments,
        }


@dataclass(frozen=True)
class AdapterPlateMeshState:
    """从场景或测试端口回读的单一板件网格状态。"""

    plate_id: str
    transaction_id: str
    object_name: str
    size_mm: Vector3Mm
    origin_offset_mm: Vector3Mm
    corner_radius_mm: float
    measured_holes: tuple[MeasuredRoundHole, ...]
    through_hole_count: int
    is_manifold: bool
    connected_components: int
    vertex_count: int
    face_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "plate_id": self.plate_id,
            "transaction_id": self.transaction_id,
            "object_name": self.object_name,
            "size_mm": list(self.size_mm),
            "origin_offset_mm": list(self.origin_offset_mm),
            "corner_radius_mm": self.corner_radius_mm,
            "measured_holes": [hole.to_dict() for hole in self.measured_holes],
            "through_hole_count": self.through_hole_count,
            "is_manifold": self.is_manifold,
            "connected_components": self.connected_components,
            "vertex_count": self.vertex_count,
            "face_count": self.face_count,
        }


@dataclass(frozen=True)
class AdapterPlateCreationPlan:
    """P1 唯一允许的转接板真实网格创建计划。"""

    schema_version: str
    plan_id: str
    source: str
    requires_confirmation: bool
    plate_id: str
    design: AdapterPlateDesign
    user_summary: str

    @property
    def action_type(self) -> str:
        return "create_adapter_plate_mesh"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "source": self.source,
            "requires_confirmation": self.requires_confirmation,
            "action": {
                "type": self.action_type,
                "plate_id": self.plate_id,
                "design": self.design.to_dict(),
            },
            "user_summary": self.user_summary,
        }


@dataclass(frozen=True)
class AdapterPlateUpdatePlan:
    """P4 唯一允许的转接板真实网格更新计划。"""

    schema_version: str
    plan_id: str
    source: str
    requires_confirmation: bool
    plate_id: str
    before_design: AdapterPlateDesign
    design: AdapterPlateDesign
    user_summary: str

    @property
    def action_type(self) -> str:
        return "update_adapter_plate_mesh"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "source": self.source,
            "requires_confirmation": self.requires_confirmation,
            "action": {
                "type": self.action_type,
                "plate_id": self.plate_id,
                "before_design": self.before_design.to_dict(),
                "design": self.design.to_dict(),
            },
            "user_summary": self.user_summary,
        }
