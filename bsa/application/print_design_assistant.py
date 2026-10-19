"""把 AI 零件候选收敛为 P2 可编辑且可验证的转接板表单。"""

from __future__ import annotations

import math

from .adapter_plate_ui import AdapterPlateForm
from ..core.adapter_plate import design_adapter_plate
from ..core.adapter_plate_mesh import adapter_plate_spec_from_design
from ..domain.adapter_plate import AdapterPlateDesign, AdapterPlateHole, AdapterPlateRevision
from ..domain.errors import DomainError, ErrorCode
from ..planner.print_intent_candidate import (
    PrintIntentCandidate,
    build_adapter_plate_revision,
)
from ..planner.print_intent_provider import PrintIntentRequest


_MAX_USER_TEXT = 1000


def _user_text(value: object, label: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}必须是文本")
    parsed = value.strip()
    if required and not parsed:
        raise ValueError(f"{label}不能为空")
    if len(parsed) > _MAX_USER_TEXT:
        raise ValueError(f"{label}不能超过 {_MAX_USER_TEXT} 个字符")
    return parsed


def build_print_intent_request(
    instruction: str,
    *,
    previous_candidate: PrintIntentCandidate | None = None,
    measurement_answers: str = "",
    current_design: AdapterPlateDesign | None = None,
) -> PrintIntentRequest:
    """构造发送前可完整预览的最小请求；不包含界面默认尺寸。"""

    intent = _user_text(instruction, "用户需求")
    answers = _user_text(measurement_answers, "补充信息", required=False)
    requested: tuple[dict[str, str], ...] = ()
    if previous_candidate is not None:
        if previous_candidate.status != "needs_input":
            raise ValueError("只有缺失测量候选可以继续补充")
        if not answers:
            raise ValueError("请先回答需要补充的测量问题")
        requested = tuple(
            measurement.to_dict()
            for measurement in previous_candidate.missing_measurements
        )
    elif answers:
        raise ValueError("没有待回答的测量问题")
    return PrintIntentRequest(
        instruction=intent,
        requested_measurements=requested,
        measurement_answers=answers,
        current_design=(current_design.to_dict() if current_design is not None else None),
    )


def print_request_preview(request: PrintIntentRequest) -> str:
    """生成给用户检查的实际发送内容摘要。"""

    lines = [f"用户需求：{request.instruction}"]
    if request.requested_measurements:
        labels = "、".join(
            str(item.get("label", "待补充尺寸"))
            for item in request.requested_measurements
        )
        lines.append(f"上一轮待补充：{labels}")
        lines.append(f"本轮补充：{request.measurement_answers}")
    if request.current_design is not None:
        design = request.current_design
        size = design.get("size_mm", ["?", "?", "?"])
        holes = design.get("holes", [])
        lines.append(f"当前零件：{design.get('plate_id', '未知')}")
        if isinstance(size, list) and len(size) == 3:
            lines.append(f"当前尺寸：{size[0]:g} × {size[1]:g} × {size[2]:g} mm")
        lines.append(f"当前结构：{len(holes) if isinstance(holes, list) else 0} 个贯穿孔")
    lines.extend(
        (
            "候选零件族：四孔矩形转接板",
            "不发送 Blender 场景、网格、图片、历史项目或 API Key。",
            "AI 只生成候选参数；确认前不会修改场景。",
        )
    )
    return "\n".join(lines)


def build_parameter_patch_revision(
    candidate: PrintIntentCandidate,
    current_design: AdapterPlateDesign,
) -> AdapterPlateRevision:
    """把受限 AI 补丁应用到当前可信设计，并累计原点补偿。"""

    current_spec = adapter_plate_spec_from_design(current_design)
    return build_adapter_plate_revision(
        candidate,
        current_spec,
        current_origin_offset_mm=current_design.origin_offset_mm,
    )


def describe_missing_measurements(candidate: PrintIntentCandidate) -> str:
    """把机器可读的测量请求转换为可操作的中文问题。"""

    if candidate.status != "needs_input" or not candidate.missing_measurements:
        raise ValueError("候选没有待补充测量")
    lines: list[str] = []
    for index, measurement in enumerate(candidate.missing_measurements, start=1):
        lines.append(f"{index}. {measurement.label}（{measurement.unit}）")
        lines.append(f"为什么要量：{measurement.reason}")
    return "\n".join(lines)


def _unsupported(message: str, **details: object) -> None:
    raise DomainError(ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY, message, dict(details))


def _pair(
    holes: tuple[AdapterPlateHole, ...],
    *,
    pattern_id: str,
    axis: str,
) -> tuple[float, float, float, float]:
    selected = tuple(hole for hole in holes if hole.pattern_id == pattern_id)
    if len(selected) != 2:
        _unsupported(f"{pattern_id} 必须正好包含两个孔", pattern_id=pattern_id)
    first, second = selected
    if not math.isclose(first.diameter_mm, second.diameter_mm, abs_tol=1e-6):
        _unsupported(f"{pattern_id} 的两个孔必须使用相同孔径", pattern_id=pattern_id)
    if axis == "x":
        if not math.isclose(first.center_mm[1], second.center_mm[1], abs_tol=1e-6):
            _unsupported("设备孔必须沿 X 轴排列", pattern_id=pattern_id)
        ordered = sorted((first, second), key=lambda hole: hole.center_mm[0])
        spacing = ordered[1].center_mm[0] - ordered[0].center_mm[0]
    else:
        if not math.isclose(first.center_mm[0], second.center_mm[0], abs_tol=1e-6):
            _unsupported("支架孔必须沿 Y 轴排列", pattern_id=pattern_id)
        ordered = sorted((first, second), key=lambda hole: hole.center_mm[1])
        spacing = ordered[1].center_mm[1] - ordered[0].center_mm[1]
    if spacing <= 0.0:
        _unsupported(f"{pattern_id} 孔距必须大于零", pattern_id=pattern_id)
    center_x = (first.center_mm[0] + second.center_mm[0]) / 2.0
    center_y = (first.center_mm[1] + second.center_mm[1]) / 2.0
    return center_x, center_y, spacing, first.diameter_mm


def form_from_design_candidate(candidate: PrintIntentCandidate) -> AdapterPlateForm:
    """仅把当前 UI 能无损表达的 AI 候选转换成表单。"""

    if candidate.status != "design_candidate" or candidate.design_spec is None:
        raise ValueError("候选不是可创建的转接板设计")
    pattern_ids = tuple(
        pattern.pattern_id for pattern in candidate.design_spec.mounting_patterns
    )
    if len(pattern_ids) != 2 or set(pattern_ids) != {"device", "support"}:
        _unsupported(
            "当前只支持 device 与 support 两组双孔",
            pattern_ids=list(pattern_ids),
        )
    design = design_adapter_plate(candidate.design_spec)
    device = _pair(design.holes, pattern_id="device", axis="x")
    support = _pair(design.holes, pattern_id="support", axis="y")
    return AdapterPlateForm(
        plate_id=candidate.design_spec.plate_id,
        width_mm=candidate.design_spec.width_mm,
        depth_mm=candidate.design_spec.depth_mm,
        thickness_mm=candidate.design_spec.thickness_mm,
        corner_radius_mm=candidate.design_spec.corner_radius_mm,
        device_center_x_mm=device[0],
        device_center_y_mm=device[1],
        device_spacing_mm=device[2],
        device_hole_diameter_mm=device[3],
        support_center_x_mm=support[0],
        support_center_y_mm=support[1],
        support_spacing_mm=support[2],
        support_hole_diameter_mm=support[3],
    )

