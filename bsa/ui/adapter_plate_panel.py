"""渐进呈现的 3D 打印矩形转接板原生侧栏。"""

from __future__ import annotations

import bpy
from urllib.parse import urlsplit

from ..application.ui_presentation import (
    POPUP_WIDTH_PX,
    text_columns,
    wrap_display_text,
)


def _width(owner: object, context: object) -> int:
    region = getattr(context, "region", None)
    ui_scale = getattr(context.preferences.system, "ui_scale", 1.0)
    pixels = (
        POPUP_WIDTH_PX * ui_scale
        if getattr(owner, "bl_idname", "") == "bsa.open_print_part"
        else getattr(region, "width", 320)
    )
    return text_columns(pixels, ui_scale=ui_scale)


def _wrapped(layout: object, text: str, *, width: int) -> None:
    for source in (text or "").splitlines() or [""]:
        for line in wrap_display_text(source, columns=width):
            layout.label(text=line)


def _primary(
    layout: object,
    operator: str,
    text: str,
    *,
    icon: str,
) -> None:
    row = layout.row()
    row.scale_y = 1.4
    if hasattr(row, "active_default"):
        row.active_default = True
    row.operator(operator, text=text, icon=icon)


def _draw_parameters(layout: object, settings: object, *, width: int) -> None:
    dimensions = layout.box()
    dimensions.label(text="零件尺寸", icon="MESH_CUBE")
    fields = dimensions.column()
    fields.use_property_split = True
    fields.use_property_decorate = False
    fields.prop(settings, "plate_id")
    fields.prop(settings, "width_mm")
    fields.prop(settings, "depth_mm")
    fields.prop(settings, "thickness_mm")
    fields.prop(settings, "corner_radius_mm")

    layout.prop(
        settings,
        "show_hole_settings",
        text="孔位参数（4 个贯穿孔）",
        emboss=False,
        icon=(
            "DISCLOSURE_TRI_DOWN"
            if settings.show_hole_settings
            else "DISCLOSURE_TRI_RIGHT"
        ),
    )
    if settings.show_hole_settings:
        device = layout.box()
        device.label(text="设备孔组 · 沿 X 轴", icon="ORIENTATION_GLOBAL")
        device_fields = device.column()
        device_fields.use_property_split = True
        device_fields.use_property_decorate = False
        device_fields.prop(settings, "device_center_x_mm")
        device_fields.prop(settings, "device_center_y_mm")
        device_fields.prop(settings, "device_spacing_mm")
        device_fields.prop(settings, "device_hole_diameter_mm")

        support = layout.box()
        support.label(text="支架孔组 · 沿 Y 轴", icon="ORIENTATION_GLOBAL")
        support_fields = support.column()
        support_fields.use_property_split = True
        support_fields.use_property_decorate = False
        support_fields.prop(settings, "support_center_x_mm")
        support_fields.prop(settings, "support_center_y_mm")
        support_fields.prop(settings, "support_spacing_mm")
        support_fields.prop(settings, "support_hole_diameter_mm")
    else:
        _wrapped(
            layout,
            (
                f"设备孔横向孔距 {settings.device_spacing_mm:g} mm；"
                f"支架孔纵向孔距 {settings.support_spacing_mm:g} mm"
            ),
            width=width,
        )


def _draw_ai_settings(layout: object, settings: object, session: object, *, width: int) -> None:
    layout.prop(
        settings,
        "show_ai_settings",
        text="AI 服务设置",
        emboss=False,
        icon=(
            "DISCLOSURE_TRI_DOWN"
            if settings.show_ai_settings
            else "DISCLOSURE_TRI_RIGHT"
        ),
    )
    if not settings.show_ai_settings:
        return
    box = layout.box()
    fields = box.column()
    fields.use_property_split = True
    fields.use_property_decorate = False
    fields.prop(session, "api_base", text="服务地址")
    fields.prop(session, "model", text="模型名称")
    fields.prop(session, "api_key", text="临时密钥")
    fields.prop(session, "output_format", text="输出格式")
    fields.prop(session, "timeout_seconds", text="超时（秒）")
    if session.connection_status == "TESTING":
        box.operator("bsa.cancel_provider_connection", text="取消连接测试", icon="CANCEL")
    else:
        box.operator("bsa.test_provider_connection", text="测试连接", icon="URL")
    _wrapped(box, session.connection_message, width=width)
    _wrapped(box, "密钥只保留在本次 Blender 会话。", width=width)


def draw_adapter_plate(owner: object, context: object) -> None:
    layout = owner.layout
    layout.use_property_decorate = False
    settings = context.scene.bsa_adapter_plate_settings
    session = context.window_manager.bsa_provider_session
    width = _width(owner, context)

    heading = layout.row()
    heading.label(text="3D 打印零件助手", icon="MESH_CUBE")
    layout.separator()

    if settings.stage == "START":
        layout.label(text="告诉我你想做什么", icon="OUTLINER_OB_LIGHT")
        _wrapped(
            layout,
            "目前支持四孔矩形转接板。描述用途、安装对象和你已经知道的尺寸。",
            width=width,
        )
        layout.prop(settings, "ai_instruction", text="需求")
        _primary(layout, "bsa.prepare_print_intent", "整理需求", icon="PLAY")
        layout.operator(
            "bsa.manual_adapter_plate",
            text="我已知道尺寸，直接填写",
            icon="TOOL_SETTINGS",
        )
        layout.separator()
        _draw_ai_settings(layout, settings, session, width=width)
        return

    if settings.stage == "AI_REVIEW":
        layout.label(text="调用前确认", icon="LOCKED")
        _wrapped(layout, settings.ai_data_preview, width=width)
        layout.separator()
        host = urlsplit(session.api_base).hostname or "未设置"
        _wrapped(
            layout,
            f"发送至：{host} · 模型：{session.model or '未设置'}",
            width=width,
        )
        _primary(layout, "bsa.start_print_intent", "同意并调用 AI", icon="URL")
        layout.operator("bsa.back_print_start", text="返回修改", icon="BACK")
        return

    if settings.stage == "AI_WORKING":
        layout.label(text="AI 正在整理需求", icon="TIME")
        _wrapped(layout, settings.ai_message, width=width)
        _wrapped(layout, "完成前不会创建或修改 Blender 物体。", width=width)
        layout.operator("bsa.cancel_print_intent", text="取消分析", icon="CANCEL")
        return

    if settings.stage == "AI_NEEDS_INPUT":
        layout.label(text="还需要这些测量", icon="QUESTION")
        _wrapped(layout, settings.ai_message, width=width)
        questions = layout.box()
        _wrapped(questions, settings.ai_questions_text, width=width)
        layout.prop(settings, "ai_answers", text="你的回答")
        _primary(layout, "bsa.prepare_print_intent", "检查补充信息", icon="PLAY")
        layout.operator(
            "bsa.manual_adapter_plate",
            text="改为直接填写全部尺寸",
            icon="TOOL_SETTINGS",
        )
        return

    if settings.stage == "AI_ERROR":
        feedback = layout.column()
        feedback.alert = True
        feedback.label(text="AI 没有完成", icon="ERROR")
        _wrapped(feedback, settings.ai_message, width=width)
        layout.operator("bsa.back_print_start", text="返回修改", icon="BACK")
        layout.separator()
        _draw_ai_settings(layout, settings, session, width=width)
        return

    if settings.stage == "REVIEW":
        layout.label(text="第 2 步 / 2 · 检查设计", icon="PREVIEW_RANGE")
        if settings.review_source == "ai":
            layout.label(text="设计来源：AI 候选 · 已通过本地检查", icon="INFO")
            _wrapped(layout, settings.ai_message, width=width)
        _wrapped(layout, settings.review_summary, width=width)
        layout.separator()
        _wrapped(layout, settings.review_details, width=width)
        layout.separator()
        _wrapped(layout, settings.review_notice, width=width)
        _primary(
            layout,
            "bsa.confirm_adapter_plate",
            "确认并创建",
            icon="CHECKMARK",
        )
        layout.operator(
            "bsa.edit_adapter_plate",
            text="返回修改",
            icon="BACK",
        )
        return

    if settings.stage == "WORKING":
        layout.label(text="正在创建并验证", icon="TIME")
        _wrapped(layout, "请稍候。失败时会自动恢复创建前场景。", width=width)
        return

    if settings.stage == "SUCCESS":
        layout.label(text="创建完成", icon="CHECKMARK")
        _wrapped(layout, settings.result_summary, width=width)
        _wrapped(layout, settings.result_detail, width=width)
        layout.separator()
        _wrapped(
            layout,
            "当前只验证 Blender 网格；尚未完成切片、实物打印和试装验证。",
            width=width,
        )
        _primary(
            layout,
            "bsa.new_adapter_plate",
            "继续创建",
            icon="FILE_REFRESH",
        )
        return

    if settings.stage == "ERROR" and settings.error_message:
        feedback = layout.column()
        feedback.alert = True
        feedback.label(text="需要修改", icon="ERROR")
        _wrapped(feedback, settings.error_message, width=width)
        layout.separator()

    layout.label(text="第 1 步 / 2 · 填写参数", icon="TOOL_SETTINGS")
    _draw_parameters(layout, settings, width=width)
    layout.separator()
    _primary(
        layout,
        "bsa.review_adapter_plate",
        "重新检查参数" if settings.stage == "ERROR" else "检查参数",
        icon="PREVIEW_RANGE",
    )
    _wrapped(layout, "仅在本机检查；此时不联网，也不修改场景。", width=width)
    layout.operator("bsa.back_print_start", text="返回需求入口", icon="BACK")


class BSA_PT_print_part_assistant(bpy.types.Panel):
    """首个面向用户的 3D 打印零件创建入口。"""

    bl_label = "3D 打印零件"
    bl_idname = "BSA_PT_print_part_assistant"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BSA"
    bl_order = 0

    def draw(self, context: object) -> None:
        draw_adapter_plate(self, context)

