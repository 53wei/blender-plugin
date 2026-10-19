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
from ..domain.adapter_plate_mesh import (
    AdapterPlateCreationPlan,
    AdapterPlateUpdatePlan,
)
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


@dataclass(frozen=True)
class AdapterPlateUpdateReview:
    """修改前只读差异；必须由本地验证后的前后设计生成。"""

    before_design: AdapterPlateDesign
    design: AdapterPlateDesign
    fingerprint: str
    summary: str
    details: str
    notice: str
    user_summary: str


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


def _update_fingerprint(
    before: AdapterPlateDesign,
    after: AdapterPlateDesign,
    user_summary: str,
) -> str:
    payload = json.dumps(
        {
            "before": before.to_dict(),
            "after": after.to_dict(),
            "user_summary": user_summary,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def review_adapter_plate_update(
    before: AdapterPlateDesign,
    after: AdapterPlateDesign,
    *,
    user_summary: str,
) -> AdapterPlateUpdateReview:
    """生成结构化更新差异，并复用服务层计划验证规则。"""

    from .adapter_plate_service import validate_adapter_plate_update_plan

    summary_text = user_summary.strip()
    if not summary_text:
        raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "修改摘要不能为空")
    probe = AdapterPlateUpdatePlan(
        schema_version="0.1",
        plan_id="update-review-probe",
        source="adapter_plate_ui",
        requires_confirmation=True,
        plate_id=before.plate_id,
        before_design=before,
        design=after,
        user_summary=summary_text,
    )
    validate_adapter_plate_update_plan(probe)
    before_width, before_depth, _ = before.size_mm
    after_width, after_depth, _ = after.size_mm
    changed = []
    unchanged = []
    if before_width != after_width:
        changed.append(f"板宽 {_number(before_width)} → {_number(after_width)} mm")
    else:
        unchanged.append(f"板宽保持 {_number(before_width)} mm")
    if before_depth != after_depth:
        changed.append(f"板深 {_number(before_depth)} → {_number(after_depth)} mm")
    else:
        unchanged.append(f"板深保持 {_number(before_depth)} mm")
    origin = after.origin_offset_mm
    details = "\n".join(
        (
            *unchanged,
            f"{len(after.holes)} 个孔的世界位置和孔径保持不变",
            (
                "模型原点补偿："
                f"({_number(origin[0])}, {_number(origin[1])}, "
                f"{_number(origin[2])}) mm"
            ),
        )
    )
    summary = "；".join(changed)
    return AdapterPlateUpdateReview(
        before_design=before,
        design=after,
        fingerprint=_update_fingerprint(before, after, summary_text),
        summary=summary,
        details=details,
        notice="修改已通过本地检查；确认前场景尚未修改。",
        user_summary=summary_text,
    )


def build_adapter_plate_update_plan(
    review: AdapterPlateUpdateReview,
    *,
    plan_id: str,
) -> AdapterPlateUpdatePlan:
    """重新构造差异并拒绝被界面或调用方篡改的更新摘要。"""

    if not isinstance(review, AdapterPlateUpdateReview):
        raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "转接板修改内容必须是严格类型")
    canonical = review_adapter_plate_update(
        review.before_design,
        review.design,
        user_summary=review.user_summary,
    )
    if canonical != review:
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "转接板修改摘要已经失效，请重新检查",
        )
    return AdapterPlateUpdatePlan(
        schema_version="0.1",
        plan_id=plan_id,
        source="adapter_plate_ui",
        requires_confirmation=True,
        plate_id=canonical.design.plate_id,
        before_design=canonical.before_design,
        design=canonical.design,
        user_summary=canonical.user_summary,
    )

