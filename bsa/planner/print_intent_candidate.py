"""不信任模型输出的 3D 打印零件候选协议。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from ..core.adapter_plate import design_adapter_plate, resize_adapter_plate
from ..domain.adapter_plate import (
    AdapterPlateDesign,
    AdapterPlateResizePatch,
    AdapterPlateRevision,
    AdapterPlateSpec,
    MountingPatternSpec,
    PatternHoleSpec,
)
from ..domain.errors import DomainError, ErrorCode


_STATUSES = frozenset({"needs_input", "design_candidate", "parameter_patch"})
_MEASUREMENT_TYPES = frozenset(
    {
        "outer_width",
        "outer_depth",
        "thickness",
        "hole_diameter",
        "hole_center_x",
        "hole_center_y",
        "clearance",
        "mounting_direction",
    }
)
_MAX_ITEMS = 20
_MAX_TEXT = 500


def _invalid(message: str, **details: object) -> None:
    raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, message, dict(details))


def _closed(
    payload: object,
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        _invalid(f"{label} 必须是对象")
    fields = set(payload)
    missing = required - fields
    unknown = fields - required - optional
    if missing or unknown:
        _invalid(
            f"{label} 包含缺失或未知字段",
            missing=sorted(missing),
            unknown=sorted(unknown),
        )
    return payload


def _text(value: object, field: str, *, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _invalid(f"{field} 必须是非空短文本", field=field)
    return value.strip()


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid(f"{field} 必须是有限数值", field=field)
    parsed = float(value)
    if not math.isfinite(parsed):
        _invalid(f"{field} 必须是有限数值", field=field)
    return parsed


def _string_list(
    value: object,
    field: str,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > _MAX_ITEMS:
        _invalid(f"{field} 必须是有界数组", field=field)
    if not allow_empty and not value:
        _invalid(f"{field} 不能为空", field=field)
    parsed = tuple(_text(item, field) for item in value)
    if len(parsed) != len(set(parsed)):
        _invalid(f"{field} 不能重复", field=field)
    return parsed


@dataclass(frozen=True)
class MeasurementRequest:
    measurement_id: str
    measurement_type: str
    target_id: str
    label: str
    reason: str
    unit: str

    def to_dict(self) -> dict[str, str]:
        return {
            "measurement_id": self.measurement_id,
            "measurement_type": self.measurement_type,
            "target_id": self.target_id,
            "label": self.label,
            "reason": self.reason,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class PrintIntentCandidate:
    """AI 可提出但不能直接执行的零件候选。"""

    schema_version: str
    status: str
    part_family: str
    assumptions: tuple[str, ...]
    user_summary: str
    missing_measurements: tuple[MeasurementRequest, ...] = ()
    design_spec: AdapterPlateSpec | None = None
    target_plate_id: str | None = None
    resize_patch: AdapterPlateResizePatch | None = None
    preserve_relations: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PrintIntentCandidate:
        if not isinstance(payload, Mapping):
            _invalid("候选结果必须是对象")
        common = {"schema_version", "status", "part_family", "assumptions", "user_summary"}
        status = payload.get("status")
        if status not in _STATUSES:
            _invalid("不支持的候选状态", status=status)
        if payload.get("schema_version") != "0.1":
            _invalid("不支持的候选协议版本")
        if payload.get("part_family") != "adapter_plate":
            _invalid("当前只支持矩形转接板", part_family=payload.get("part_family"))

        assumptions = _string_list(payload.get("assumptions"), "assumptions")
        summary = _text(payload.get("user_summary"), "user_summary")
        base = dict(
            schema_version="0.1",
            status=status,
            part_family="adapter_plate",
            assumptions=assumptions,
            user_summary=summary,
        )

        if status == "needs_input":
            data = _closed(
                payload,
                required=common | {"missing_measurements"},
                label="needs_input",
            )
            raw_items = data["missing_measurements"]
            if (
                not isinstance(raw_items, list)
                or not raw_items
                or len(raw_items) > _MAX_ITEMS
            ):
                _invalid("missing_measurements 必须是非空有界数组")
            measurements = tuple(_parse_measurement(item) for item in raw_items)
            ids = tuple(item.measurement_id for item in measurements)
            if len(ids) != len(set(ids)):
                _invalid("measurement_id 不能重复")
            return cls(**base, missing_measurements=measurements)

        if status == "design_candidate":
            data = _closed(
                payload,
                required=common | {"design"},
                label="design_candidate",
            )
            return cls(**base, design_spec=_parse_adapter_plate_spec(data["design"]))

        data = _closed(
            payload,
            required=common
            | {"target_plate_id", "patch", "preserve_relations"},
            label="parameter_patch",
        )
        relations = _string_list(
            data["preserve_relations"],
            "preserve_relations",
            allow_empty=False,
        )
        if relations != ("hole_world_centers",):
            _invalid(
                "P0 修改必须保持孔的世界位置",
                preserve_relations=list(relations),
            )
        return cls(
            **base,
            target_plate_id=_text(data["target_plate_id"], "target_plate_id"),
            resize_patch=_parse_resize_patch(data["patch"]),
            preserve_relations=relations,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "status": self.status,
            "part_family": self.part_family,
        }
        if self.status == "needs_input":
            payload["missing_measurements"] = [
                item.to_dict() for item in self.missing_measurements
            ]
        elif self.status == "design_candidate":
            if self.design_spec is None:
                _invalid("design_candidate 缺少设计规格")
            payload["design"] = self.design_spec.to_dict()
        elif self.status == "parameter_patch":
            if self.resize_patch is None or self.target_plate_id is None:
                _invalid("parameter_patch 缺少修改规格")
            payload["target_plate_id"] = self.target_plate_id
            payload["patch"] = self.resize_patch.to_dict()
            payload["preserve_relations"] = list(self.preserve_relations)
        else:
            _invalid("不支持的候选状态", status=self.status)
        payload["assumptions"] = list(self.assumptions)
        payload["user_summary"] = self.user_summary
        return payload


def _parse_measurement(payload: object) -> MeasurementRequest:
    fields = {
        "measurement_id",
        "measurement_type",
        "target_id",
        "label",
        "reason",
        "unit",
    }
    data = _closed(payload, required=fields, label="measurement")
    measurement_type = _text(data["measurement_type"], "measurement_type")
    if measurement_type not in _MEASUREMENT_TYPES:
        _invalid("不支持的测量类型", measurement_type=measurement_type)
    if data["unit"] != "mm":
        _invalid("P0 长度单位必须为 mm")
    return MeasurementRequest(
        measurement_id=_text(data["measurement_id"], "measurement_id"),
        measurement_type=measurement_type,
        target_id=_text(data["target_id"], "target_id"),
        label=_text(data["label"], "label"),
        reason=_text(data["reason"], "reason"),
        unit="mm",
    )


def _parse_adapter_plate_spec(payload: object) -> AdapterPlateSpec:
    fields = {
        "plate_id",
        "width_mm",
        "depth_mm",
        "thickness_mm",
        "corner_radius_mm",
        "mounting_patterns",
    }
    data = _closed(payload, required=fields, label="adapter_plate design")
    raw_patterns = data["mounting_patterns"]
    if not isinstance(raw_patterns, list) or len(raw_patterns) > _MAX_ITEMS:
        _invalid("mounting_patterns 必须是有界数组")
    patterns = tuple(_parse_pattern(item) for item in raw_patterns)
    return AdapterPlateSpec(
        plate_id=_text(data["plate_id"], "plate_id"),
        width_mm=_number(data["width_mm"], "width_mm"),
        depth_mm=_number(data["depth_mm"], "depth_mm"),
        thickness_mm=_number(data["thickness_mm"], "thickness_mm"),
        corner_radius_mm=_number(data["corner_radius_mm"], "corner_radius_mm"),
        mounting_patterns=patterns,
    )


def _parse_pattern(payload: object) -> MountingPatternSpec:
    fields = {"pattern_id", "origin_x_mm", "origin_y_mm", "holes"}
    data = _closed(payload, required=fields, label="mounting_pattern")
    raw_holes = data["holes"]
    if (
        not isinstance(raw_holes, list)
        or not raw_holes
        or len(raw_holes) > _MAX_ITEMS
    ):
        _invalid("holes 必须是非空有界数组")
    holes = tuple(_parse_hole(item) for item in raw_holes)
    return MountingPatternSpec(
        pattern_id=_text(data["pattern_id"], "pattern_id"),
        origin_x_mm=_number(data["origin_x_mm"], "origin_x_mm"),
        origin_y_mm=_number(data["origin_y_mm"], "origin_y_mm"),
        holes=holes,
    )


def _parse_hole(payload: object) -> PatternHoleSpec:
    fields = {"hole_id", "offset_x_mm", "offset_y_mm", "diameter_mm"}
    data = _closed(payload, required=fields, label="pattern hole")
    return PatternHoleSpec(
        hole_id=_text(data["hole_id"], "hole_id"),
        offset_x_mm=_number(data["offset_x_mm"], "offset_x_mm"),
        offset_y_mm=_number(data["offset_y_mm"], "offset_y_mm"),
        diameter_mm=_number(data["diameter_mm"], "diameter_mm"),
    )


def _parse_resize_patch(payload: object) -> AdapterPlateResizePatch:
    required = {"fixed_x_edge", "fixed_y_edge", "preserve_pattern_ids"}
    optional = {"new_width_mm", "new_depth_mm"}
    data = _closed(
        payload,
        required=required,
        optional=optional,
        label="adapter_plate patch",
    )
    if "new_width_mm" not in data and "new_depth_mm" not in data:
        _invalid("patch 必须提供新宽度或新深度")
    fixed_x = _text(data["fixed_x_edge"], "fixed_x_edge")
    fixed_y = _text(data["fixed_y_edge"], "fixed_y_edge")
    if fixed_x not in {"left", "center", "right"}:
        _invalid("fixed_x_edge 不受支持")
    if fixed_y not in {"front", "center", "back"}:
        _invalid("fixed_y_edge 不受支持")
    return AdapterPlateResizePatch(
        new_width_mm=(
            _number(data["new_width_mm"], "new_width_mm")
            if "new_width_mm" in data
            else None
        ),
        new_depth_mm=(
            _number(data["new_depth_mm"], "new_depth_mm")
            if "new_depth_mm" in data
            else None
        ),
        fixed_x_edge=fixed_x,
        fixed_y_edge=fixed_y,
        preserve_pattern_ids=_string_list(
            data["preserve_pattern_ids"],
            "preserve_pattern_ids",
            allow_empty=False,
        ),
    )


def build_adapter_plate_design(candidate: PrintIntentCandidate) -> AdapterPlateDesign:
    """对 AI 设计候选执行本地几何验证。"""
    if candidate.status != "design_candidate" or candidate.design_spec is None:
        _invalid("候选不是转接板设计")
    return design_adapter_plate(candidate.design_spec)


def build_adapter_plate_revision(
    candidate: PrintIntentCandidate,
    current_spec: AdapterPlateSpec,
    *,
    current_origin_offset_mm: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> AdapterPlateRevision:
    """把 AI 修改候选应用到本地可信的当前规格。"""
    if candidate.status != "parameter_patch" or candidate.resize_patch is None:
        _invalid("候选不是转接板参数修改")
    if candidate.target_plate_id != current_spec.plate_id:
        raise DomainError(
            ErrorCode.OBJECT_NOT_FOUND,
            "修改目标不是当前转接板",
            {
                "target_plate_id": candidate.target_plate_id,
                "current_plate_id": current_spec.plate_id,
            },
        )
    return resize_adapter_plate(
        current_spec,
        candidate.resize_patch,
        origin_offset_mm=current_origin_offset_mm,
    )


def print_intent_json_schema() -> dict[str, Any]:
    """返回首个转接板 AI 候选的关闭字段 JSON Schema。"""

    def closed(
        properties: dict[str, Any],
        *,
        required: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "required": required if required is not None else list(properties),
            "additionalProperties": False,
        }
        if extra:
            result.update(extra)
        return result

    text = {"type": "string", "minLength": 1, "maxLength": _MAX_TEXT}
    finite_number = {"type": "number"}
    positive_number = {"type": "number", "exclusiveMinimum": 0}
    assumptions = {"type": "array", "items": text, "maxItems": _MAX_ITEMS}
    common = {
        "schema_version": {"type": "string", "const": "0.1"},
        "part_family": {"type": "string", "const": "adapter_plate"},
        "assumptions": assumptions,
        "user_summary": text,
    }
    measurement = closed(
        {
            "measurement_id": text,
            "measurement_type": {
                "type": "string",
                "enum": sorted(_MEASUREMENT_TYPES),
            },
            "target_id": text,
            "label": text,
            "reason": text,
            "unit": {"type": "string", "const": "mm"},
        }
    )
    hole = closed(
        {
            "hole_id": text,
            "offset_x_mm": finite_number,
            "offset_y_mm": finite_number,
            "diameter_mm": positive_number,
        }
    )
    pattern = closed(
        {
            "pattern_id": text,
            "origin_x_mm": finite_number,
            "origin_y_mm": finite_number,
            "holes": {
                "type": "array",
                "items": hole,
                "minItems": 1,
                "maxItems": _MAX_ITEMS,
            },
        }
    )
    design = closed(
        {
            "plate_id": text,
            "width_mm": positive_number,
            "depth_mm": positive_number,
            "thickness_mm": positive_number,
            "corner_radius_mm": {"type": "number", "minimum": 0},
            "mounting_patterns": {
                "type": "array",
                "items": pattern,
                "maxItems": _MAX_ITEMS,
            },
        }
    )
    patch_properties = {
        "new_width_mm": positive_number,
        "new_depth_mm": positive_number,
        "fixed_x_edge": {
            "type": "string",
            "enum": ["left", "center", "right"],
        },
        "fixed_y_edge": {
            "type": "string",
            "enum": ["front", "center", "back"],
        },
        "preserve_pattern_ids": {
            "type": "array",
            "items": text,
            "minItems": 1,
            "maxItems": _MAX_ITEMS,
            "uniqueItems": True,
        },
    }
    patch = closed(
        patch_properties,
        required=["fixed_x_edge", "fixed_y_edge", "preserve_pattern_ids"],
        extra={
            "anyOf": [
                {"required": ["new_width_mm"]},
                {"required": ["new_depth_mm"]},
            ]
        },
    )

    needs_input = closed(
        {
            **common,
            "status": {"type": "string", "const": "needs_input"},
            "missing_measurements": {
                "type": "array",
                "items": measurement,
                "minItems": 1,
                "maxItems": _MAX_ITEMS,
            },
        }
    )
    design_candidate = closed(
        {
            **common,
            "status": {"type": "string", "const": "design_candidate"},
            "design": design,
        }
    )
    parameter_patch = closed(
        {
            **common,
            "status": {"type": "string", "const": "parameter_patch"},
            "target_plate_id": text,
            "patch": patch,
            "preserve_relations": {
                "type": "array",
                "prefixItems": [
                    {"type": "string", "const": "hole_world_centers"}
                ],
                "minItems": 1,
                "maxItems": 1,
            },
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "oneOf": [needs_input, design_candidate, parameter_patch],
    }
