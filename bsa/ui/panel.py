"""简洁的 Blender 原生助手：阶段先行，设置按需展开。"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import bpy

from ..application.assistant_state import AssistantStatus
from ..application.ui_presentation import (
    POPUP_WIDTH_PX,
    phase_for,
    planning_config_issue,
    text_columns,
    wrap_display_text,
)


def _draw_wrapped(layout: object, text: str, *, width: int) -> None:
    """按实际显示宽度画完整文本，不截断动作或用户数据。"""
    for line in wrap_display_text(text, columns=width):
        layout.label(text=line)


def _primary(layout: object, operator: str, text: str, *, enabled: bool = True,
             icon: str = "PLAY") -> None:
    """一个阶段只强调一个下一步；禁用控件仍保留明确标签。"""
    row = layout.row()
    row.enabled = enabled
    row.scale_y = 1.45
    if hasattr(row, "active_default"):
        row.active_default = True
    row.operator(operator, text=text, icon=icon)


def _disclosure(layout: object, owner: object, name: str, text: str) -> None:
    """使用原生展开按钮，避免装饰性容器反复嵌套。"""
    layout.prop(
        owner, name, text=text, emboss=False,
        icon="DISCLOSURE_TRI_DOWN" if getattr(owner, name) else "DISCLOSURE_TRI_RIGHT",
    )


def _draw_settings(layout: object, context: object, *, width: int) -> None:
    """设置是独立视图；返回主界面不会清掉待确认的计划。"""
    settings = context.scene.bsa_settings
    provider = context.window_manager.bsa_provider_session
    layout.label(text="AI 服务", icon="URL")
    fields = layout.column()
    fields.use_property_split = True
    fields.use_property_decorate = False
    fields.enabled = settings.assistant_status != AssistantStatus.PLANNING.value
    fields.prop(provider, "api_base", text="服务地址")
    fields.prop(provider, "model", text="模型名称")
    fields.prop(provider, "api_key", text="临时密钥")
    fields.prop(provider, "output_format")
    fields.prop(provider, "timeout_seconds")
    _draw_wrapped(layout, "密钥仅用于当前会话。本机服务未开启认证时可留空。", width=width)
    if provider.connection_status == "TESTING":
        layout.operator("bsa.cancel_provider_connection", text="取消连接测试", icon="CANCEL")
    else:
        layout.operator("bsa.test_provider_connection", text="测试连接", icon="URL")
    if provider.connection_status != "NOT_TESTED":
        _draw_wrapped(layout, provider.connection_message, width=width)
    if provider.connection_status == "SUCCESS" and provider.available_models_text:
        _disclosure(layout, provider, "show_model_names", "可用模型名称（最多显示 8 个）")
        if provider.show_model_names:
            _draw_wrapped(layout, provider.available_models_text, width=width)
    if provider.output_format == "json_schema":
        _draw_wrapped(layout, "本机地址：http://127.0.0.1:1234/v1", width=width)

    layout.separator()
    _disclosure(layout, settings, "show_manual_controls", "精确控制")
    if settings.show_manual_controls:
        manual = layout.column()
        manual.use_property_split = True
        manual.use_property_decorate = False
        manual.enabled = settings.assistant_status not in {"PLANNING", "WORKING"}
        manual.prop(settings, "source_object", text="移动物体")
        manual.prop(settings, "target_object", text="目标表面")
        manual.prop(settings, "region", text="表面区域")
        manual.prop(settings, "clearance", text="表面间隙")
        manual.prop(settings, "lock_target")
        source, target = settings.source_object, settings.target_object
        row = manual.row()
        row.enabled = source is not None and target is not None and source != target
        row.operator("bsa.preview_plan", text="生成精确计划", icon="PREVIEW_RANGE")
        if source is not None and source == target:
            _draw_wrapped(layout, "移动物体和目标不能相同。", width=width)

    layout.separator()
    layout.prop(settings, "show_avatar", text="显示右下角小助手")
    if provider.last_plan_source == "llm":
        layout.separator()
        _disclosure(layout, provider, "show_usage_details", "最近一次 AI 用量")
        if provider.show_usage_details:
            _draw_wrapped(layout, "模型：" + provider.last_model, width=width)
            if provider.last_usage_available:
                _draw_wrapped(layout, (
                    f"Token：输入 {provider.last_input_tokens}，输出 {provider.last_output_tokens}"
                ), width=width)
            else:
                layout.label(text="服务未返回 Token 用量")
            _draw_wrapped(layout, (
                f"请求 {provider.last_request_count} 次，修复 {provider.last_repair_count} 次，"
                f"耗时 {provider.last_planning_latency_ms} ms"
            ), width=width)


def _draw_input(layout: object, context: object, *, width: int, retry: bool = False) -> None:
    """首屏以指令为主；对象名称和一个真实可用例子足够指路。"""
    settings = context.scene.bsa_settings
    layout.label(text="你想怎么调整？")
    row = layout.row()
    row.scale_y = 1.35
    row.prop(settings, "instruction", text="")
    _primary(
        layout, "bsa.preview_instruction", "重新生成计划" if retry else "生成计划",
        enabled=bool(settings.instruction.strip()), icon="PREVIEW_RANGE",
    )
    selected = getattr(context, "active_object", None)
    if selected is not None:
        _draw_wrapped(layout, "当前选中：" + selected.name, width=width)
        _draw_wrapped(layout, f"示例：{selected.name} 向右移动 20 厘米", width=width)
    else:
        _draw_wrapped(layout, "示例：把 Lamp 放到 Desk 右侧", width=width)
    _draw_wrapped(layout, "先生成计划，确认后才修改场景。", width=width)


def _draw_review(layout: object, context: object, *, width: int) -> None:
    """简短摘要和完整详情共存，仍由用户明确同意发送。"""
    provider = context.window_manager.bsa_provider_session
    try:
        pending = json.loads(provider.pending_context_json)
        scene_context = pending["scene_context"]
        objects = scene_context["objects"]
        names = [str(obj["name"]) for obj in objects]
        if not isinstance(scene_context, dict) or not isinstance(objects, list):
            raise ValueError("Invalid pending context")
    except (TypeError, ValueError, KeyError):
        _draw_wrapped(layout, "发送数据已失效，请重新生成计划。", width=width)
        _primary(layout, "bsa.preview_instruction", "重新生成计划", icon="FILE_REFRESH")
        return

    _draw_wrapped(layout, "只发送本条要求和下列对象的摘要，不发送网格或文件。", width=width)
    _draw_wrapped(layout, "要求：" + str(pending["instruction"]), width=width)
    _draw_wrapped(layout, f"对象（{len(names)}）：" + "、".join(names), width=width)
    _draw_wrapped(layout, f"场景单位比例：{scene_context.get('unit_scale', 1.0)}", width=width)
    _draw_wrapped(layout, "对象字段：名称、ID、类型、位置、尺寸和锁定状态。", width=width)
    _draw_wrapped(layout, "模型：" + (provider.model or "未设置"), width=width)
    try:
        host = urlsplit(provider.api_base).hostname or "未设置"
    except ValueError:
        host = "地址无效"
    _draw_wrapped(layout, "服务地址：" + host, width=width)
    _disclosure(layout, provider, "show_data_details", "完整发送详情")
    if provider.show_data_details:
        _draw_wrapped(layout, provider.pending_data_preview, width=width)
    layout.separator()
    issue = planning_config_issue(
        provider.api_base, provider.model, provider.timeout_seconds, provider.output_format
    )
    if issue:
        _draw_wrapped(layout, issue, width=width)
        _primary(layout, "bsa.toggle_settings", "设置 AI 服务", icon="PREFERENCES")
    else:
        _primary(layout, "bsa.start_ai_planning", "同意发送并生成计划", icon="CHECKMARK")
    layout.operator("bsa.discard_ai_request", text="不发送，返回输入", icon="BACK")
    _draw_wrapped(layout, "现在尚未联网，场景没有修改。", width=width)


def draw_assistant(owner: object, context: object) -> None:
    """面板与浮窗共享同一阶段界面，绘制不修改任何对象。"""
    layout = owner.layout
    layout.use_property_decorate = False
    settings = context.scene.bsa_settings
    provider = context.window_manager.bsa_provider_session
    status = AssistantStatus(settings.assistant_status)
    phase = phase_for(status)
    ui_scale = getattr(context.preferences.system, "ui_scale", 1.0)
    is_popup = getattr(owner, "bl_idname", "") == "bsa.open_assistant"
    region = getattr(context, "region", None)
    pixels = POPUP_WIDTH_PX * ui_scale if is_popup else getattr(region, "width", 320)
    width = text_columns(pixels, ui_scale=ui_scale)

    header = layout.row(align=True)
    header.label(text="设置" if provider.show_settings else phase.title, icon=phase.icon)
    header.operator(
        "bsa.toggle_settings", text="返回助手" if provider.show_settings else "设置",
        icon="BACK" if provider.show_settings else "PREFERENCES",
    )
    layout.separator()
    if provider.show_settings:
        _draw_settings(layout, context, width=width)
        return

    if status is AssistantStatus.ERROR:
        feedback = layout.column()
        feedback.alert = True
        _draw_wrapped(feedback, settings.result_text, width=width)
        if settings.result_detail:
            _draw_wrapped(layout, settings.result_detail, width=width)
        layout.separator()
        _draw_input(layout, context, width=width, retry=True)
    elif status is AssistantStatus.IDLE:
        _draw_input(layout, context, width=width)
    elif status is AssistantStatus.AI_REVIEW:
        _draw_review(layout, context, width=width)
    elif status is AssistantStatus.PLANNING:
        _draw_wrapped(layout, "正在等待 AI 返回候选计划。", width=width)
        _draw_wrapped(layout, "这时不会修改场景，可以随时取消。", width=width)
        _primary(layout, "bsa.cancel_ai_planning", "取消生成", icon="CANCEL")
    elif status is AssistantStatus.PLAN_READY and settings.plan_json:
        _draw_wrapped(layout, settings.preview_text, width=width)
        if provider.last_plan_source == "llm":
            _draw_wrapped(layout, "计划来源：AI，模型 " + provider.last_model, width=width)
        else:
            layout.label(text="计划来源：本地，不调用 AI")
        layout.separator()
        _primary(layout, "bsa.confirm_plan", "确认并执行", icon="CHECKMARK")
        layout.operator("bsa.clear", text="放弃计划，返回输入", icon="BACK")
        _draw_wrapped(layout, "确认前，场景没有修改。", width=width)
    elif status is AssistantStatus.WORKING:
        _draw_wrapped(layout, "正在执行并验证。请等待结果。", width=width)
    elif status is AssistantStatus.SUCCESS:
        _draw_wrapped(layout, settings.result_text, width=width)
        if settings.result_detail:
            _draw_wrapped(layout, settings.result_detail, width=width)
        layout.separator()
        _primary(layout, "bsa.clear", "继续调整", icon="FILE_REFRESH")
    else:
        _draw_wrapped(layout, "计划已失效，请重新生成。", width=width)
        _primary(layout, "bsa.clear", "返回输入", icon="BACK")


class BSA_PT_scene_assistant(bpy.types.Panel):
    """简洁助手侧栏；备用入口保持 Blender 4.5 可显示的 BSA。"""

    bl_label = "场景领航员"
    bl_idname = "BSA_PT_scene_assistant"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BSA"

    def draw(self, context: object) -> None:
        draw_assistant(self, context)
