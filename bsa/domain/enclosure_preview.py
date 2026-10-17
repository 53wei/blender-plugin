"""参数化外壳装配预览的严格类型化协议。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .enclosure import EnclosureDesign

Vector3Mm = tuple[float, float, float]


@dataclass(frozen=True)
class EnclosurePartSpec:
    """一个待创建预览部件；坐标和尺寸单位均为毫米。"""

    part_id: str
    part_type: str
    shape: str
    center_mm: Vector3Mm
    dimensions_mm: Vector3Mm
    display_mode: str = "solid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "part_type": self.part_type,
            "shape": self.shape,
            "center_mm": list(self.center_mm),
            "dimensions_mm": list(self.dimensions_mm),
            "display_mode": self.display_mode,
        }


@dataclass(frozen=True)
class EnclosurePartState:
    """由执行器回读的预览部件状态。"""

    enclosure_id: str
    transaction_id: str
    part_id: str
    part_type: str
    shape: str
    center_mm: Vector3Mm
    dimensions_mm: Vector3Mm
    display_mode: str


@dataclass(frozen=True)
class EnclosurePreviewPlan:
    """P1 唯一允许的外壳创建计划。"""

    schema_version: str
    plan_id: str
    source: str
    requires_confirmation: bool
    enclosure_id: str
    design: EnclosureDesign
    user_summary: str

    @property
    def action_type(self) -> str:
        return "create_enclosure_preview"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "source": self.source,
            "requires_confirmation": self.requires_confirmation,
            "action": {
                "type": self.action_type,
                "enclosure_id": self.enclosure_id,
                "design": self.design.to_dict(),
            },
            "user_summary": self.user_summary,
        }
