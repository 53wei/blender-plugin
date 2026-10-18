"""不依赖 Blender 的转接板表单映射、摘要与确认计划构造。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass

from ..core.adapter_plate import design_adapter_plate
from ..domain.adapter_plate import (
    AdapterPlateDesign,
    AdapterPlateSpec,
    MountingPatternSpec,
    PatternHoleSpec,
)
from ..domain.adapter_plate_mesh import AdapterPlateCreationPlan
from ..domain.errors import DomainError, ErrorCode

_SAFE_PLATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class AdapterPlateForm:
    """P2 原生界面公开的最小矩形转接板参数，长度单位均为毫米。"""

    plate_id: str
    width_mm: float
    depth_mm: float
    thickness_mm: float
    corner_radius_mm: float
    device_center_x_mm: float
    device_center_y_mm: float
    device_spacing_mm: float
    device_hole_diameter_mm: float
    support_center_x_mm: float
    support_center_y_mm: float
    support_spacing_mm: float
    support_hole_diameter_mm: float


@dataclass(frozen=True)
class AdapterPlateReview:
    """确认前的只读结果；它只能由本模块从完整表单重新构造。"""

    form: AdapterPlateForm
    design: AdapterPlateDesign
    fingerprint: str
    summary: str
    details: str
    notice: str


def _number(value: float) -> str:
    return f"{value:g}"


def _fingerprint(form: AdapterPlateForm) -> str:
    payload = json.dumps(
        asdict(form),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validated_spec(form: AdapterPlateForm) -> AdapterPlateSpec:
    if not isinstance(form.plate_id, str) or not _SAFE_PLATE_ID.fullmatch(
        form.plate_id
    ):
        raise DomainError(
            ErrorCode.PRINT_SPEC_INVALID,
            "零件编号只能使用字母、数字、点、下划线和连字符",
            {"field": "plate_id"},
        )
    for field, value in (
        ("device_spacing_mm", form.device_spacing_mm),
        ("support_spacing_mm", form.support_spacing_mm),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0.0
        ):
            raise DomainError(
                ErrorCode.PRINT_SPEC_INVALID,
                f"{field} 必须是正有限数值",
                {"field": field},
            )
    return AdapterPlateSpec(
        plate_id=form.plate_id,
        width_mm=form.width_mm,
        depth_mm=form.depth_mm,
        thickness_mm=form.thickness_mm,
        corner_radius_mm=form.corner_radius_mm,
        mounting_patterns=(
            MountingPatternSpec(
                pattern_id="device",
                origin_x_mm=form.device_center_x_mm,
                origin_y_mm=form.device_center_y_mm,
                holes=(
                    PatternHoleSpec(
                        hole_id="device-left",
                        offset_x_mm=-form.device_spacing_mm / 2.0,
                        offset_y_mm=0.0,
                        diameter_mm=form.device_hole_diameter_mm,
                    ),
                    PatternHoleSpec(
                        hole_id="device-right",
                        offset_x_mm=form.device_spacing_mm / 2.0,
                        offset_y_mm=0.0,
                        diameter_mm=form.device_hole_diameter_mm,
                    ),
                ),
            ),
            MountingPatternSpec(
                pattern_id="support",
                origin_x_mm=form.support_center_x_mm,
                origin_y_mm=form.support_center_y_mm,
                holes=(
                    PatternHoleSpec(
                        hole_id="support-front",
                        offset_x_mm=0.0,
                        offset_y_mm=-form.support_spacing_mm / 2.0,
                        diameter_mm=form.support_hole_diameter_mm,
                    ),
                    PatternHoleSpec(
                        hole_id="support-back",
                        offset_x_mm=0.0,
                        offset_y_mm=form.support_spacing_mm / 2.0,
                        diameter_mm=form.support_hole_diameter_mm,
                    ),
                ),
            ),
        ),
    )


def review_adapter_plate_form(form: AdapterPlateForm) -> AdapterPlateReview:
    """严格检查界面参数并生成只读摘要；本函数绝不修改 Blender。"""
    design = design_adapter_plate(_validated_spec(form))
    width, depth, thickness = design.size_mm
    summary = (
        f"矩形转接板 {_number(width)} × {_number(depth)} × "
        f"{_number(thickness)} mm；{len(design.holes)} 个贯穿孔"
    )
    details = "\n".join(
        (
            f"外形：圆角半径 {_number(design.corner_radius_mm)} mm",
            (
                "设备孔组：横向孔距 "
                f"{_number(form.device_spacing_mm)} mm，孔径 "
                f"{_number(form.device_hole_diameter_mm)} mm，中心 "
                f"({_number(form.device_center_x_mm)}, "
                f"{_number(form.device_center_y_mm)}) mm"
            ),
            (
                "支架孔组：纵向孔距 "
                f"{_number(form.support_spacing_mm)} mm，孔径 "
                f"{_number(form.support_hole_diameter_mm)} mm，中心 "
                f"({_number(form.support_center_x_mm)}, "
                f"{_number(form.support_center_y_mm)}) mm"
            ),
        )
    )
    return AdapterPlateReview(
        form=form,
        design=design,
        fingerprint=_fingerprint(form),
        summary=summary,
        details=details,
        notice="参数已通过本地检查；确认前场景尚未修改。",
    )


def build_adapter_plate_creation_plan(
    review: AdapterPlateReview,
    *,
    plan_id: str,
) -> AdapterPlateCreationPlan:
    """重新验证摘要来源，再构造唯一允许的创建计划。"""
    if not isinstance(review, AdapterPlateReview):
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "转接板确认内容必须是严格类型",
        )
    canonical = review_adapter_plate_form(review.form)
    if (
        canonical.fingerprint != review.fingerprint
        or canonical.design != review.design
        or canonical.summary != review.summary
    ):
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "转接板检查摘要已经失效，请重新检查参数",
        )
    return AdapterPlateCreationPlan(
        schema_version="0.1",
        plan_id=plan_id,
        source="adapter_plate_ui",
        requires_confirmation=True,
        plate_id=canonical.design.plate_id,
        design=canonical.design,
        user_summary=canonical.summary,
    )

