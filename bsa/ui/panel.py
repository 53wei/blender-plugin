"""场景领航员的对话式 Blender 原生界面。"""

from __future__ import annotations

import textwrap

import bpy

from ..application.assistant_state import AssistantStatus, presentation_for
from .avatar import assistant_icon_id


def _draw_wrapped(layout: object, text: str, *, width: int = 30) -> None:
    """把长消息拆成 Blender 能稳定显示的多行标签。"""

    source_lines = (text or "").splitlines() or [""]
    for source_line in source_lines:
        for line in textwrap.wrap(
            source_line,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]:
            layout.label(text=line)


class BSA_PT_scene_assistant(bpy.types.Panel):
    """对话、计划确认和验证结果面板。"""

    bl_label = "场景领航员"
    bl_idname = "BSA_PT_scene_assistant"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    # Blender 4.5 的竖排侧栏分类不能可靠显示中文，会变成 UNSUPPORTED。
    # 因此分类使用稳定的 ASCII 缩写，面板内容保持全中文。
    bl_category = "BSA"

    def draw(self, context: object) -> None:
        layout = self.layout
        settings = context.scene.bsa_settings
        status = presentation_for(AssistantStatus(settings.assistant_status))
        source = settings.source_object
        target = settings.target_object
        selection_ready = source is not None and target is not None and source != target

        header = layout.box()
        split = header.split(factor=0.30)
        image_column = split.column()
        image_column.template_icon(icon_value=assistant_icon_id(), scale=4.5)
        status_column = split.column(align=True)
        status_column.label(text=f"场景领航员 · {status.label}", icon=status.icon)
        _draw_wrapped(status_column, status.detail, width=22)
        header.prop(settings, "show_avatar", toggle=True)

        steps = layout.row(align=True)
        steps.prop(settings, "workflow_section", expand=True)

        selected_meshes = tuple(
            obj for obj in context.selected_objects if obj.type == "MESH"
        )
        if settings.workflow_section == "MODEL":
            model_box = layout.box()
            model_box.label(text="第 1 步 · 导入已有模型", icon="FILE_FOLDER")
            model_box.operator("bsa.import_models", text="选择一个或多个模型文件")
            model_box.label(text="支持：BLEND、FBX、OBJ、GLB/GLTF、STL、PLY")
            model_box.label(text="导入成功后会自动选中新模型", icon="INFO")
        elif settings.workflow_section == "PLACE":
            placement_box = layout.box()
            placement_box.label(text="第 2 步 · 调整所选模型", icon="OBJECT_DATA")
            placement_box.label(text=f"当前选中 {len(selected_meshes)} 个网格物体")
            placement_box.operator("bsa.preview_ground", text="落到地面")

            grid_row = placement_box.row(align=True)
            grid_row.prop(settings, "grid_columns")
            grid_row.prop(settings, "layout_gap")
            placement_box.operator("bsa.preview_grid", text="网格排列")

            align_row = placement_box.row(align=True)
            align_row.prop(settings, "layout_axis", expand=True)
            placement_box.prop(settings, "align_anchor")
            placement_box.operator("bsa.preview_align", text="按活动物体对齐")

            rotate_row = placement_box.row(align=True)
            rotate_row.prop(settings, "rotation_axis", expand=True)
            rotate_row.prop(settings, "rotation_degrees")
            rotate_row.operator("bsa.preview_rotate", text="旋转")
            scale_row = placement_box.row(align=True)
            scale_row.prop(settings, "scale_factor")
            scale_row.operator("bsa.preview_scale", text="等比缩放")
            placement_box.label(
                text="以上操作都会先生成动作清单，再由你确认",
                icon="LOCKED",
            )
        elif settings.workflow_section == "CAMERA":
            camera_box = layout.box()
            camera_box.label(text="第 3 步 · 自动取景与导出", icon="CAMERA_DATA")
            camera_box.prop(settings, "camera_scope", expand=True)
            camera_box.prop(settings, "camera_lens_mm")
            camera_box.prop(settings, "camera_margin")
            size_row = camera_box.row(align=True)
            size_row.prop(settings, "render_width")
            size_row.prop(settings, "render_height")
            camera_box.prop(settings, "render_transparent")
            camera_box.operator("bsa.preview_camera", text="生成取景预览")
            if settings.camera_plan_json:
                preview = camera_box.box()
                preview.label(text="应用前确认", icon="PREVIEW_RANGE")
                _draw_wrapped(preview, settings.camera_preview_text, width=48)
                actions = preview.row(align=True)
                actions.operator(
                    "bsa.confirm_camera",
                    text="确认并应用相机",
                    icon="CHECKMARK",
                )
            camera_box.operator("bsa.export_png", text="导出 PNG", icon="IMAGE_DATA")

        if settings.assistant_status not in {
            AssistantStatus.AI_REVIEW.value,
            AssistantStatus.PLANNING.value,
        }:
            conversation = layout.box()
            conversation.label(text="对话", icon="COMMUNITY")
            if settings.last_user_message:
                conversation.label(text="你", icon="USER")
                _draw_wrapped(conversation, settings.last_user_message)
            conversation.label(text="场景领航员", icon="OUTLINER_OB_LIGHT")
            _draw_wrapped(conversation, settings.last_assistant_message)

        provider = context.window_manager.bsa_provider_session
        provider_box = layout.box()
        provider_box.prop(
            provider,
            "show_provider_settings",
            text="AI 服务连接",
            icon=(
                "DISCLOSURE_TRI_DOWN"
                if provider.show_provider_settings
                else "DISCLOSURE_TRI_RIGHT"
            ),
            emboss=False,
        )
        status_labels = {
            "NOT_TESTED": ("尚未测试", "QUESTION"),
            "TESTING": ("正在测试连接", "TIME"),
            "SUCCESS": ("连接成功", "CHECKMARK"),
            "ERROR": ("连接失败", "ERROR"),
            "CANCELED": ("连接测试已取消", "CANCEL"),
        }
        status_label, status_icon = status_labels[provider.connection_status]
        provider_box.label(text=status_label, icon=status_icon)
        if provider.show_provider_settings:
            provider_box.prop(provider, "provider_type")
            provider_box.prop(provider, "api_base")
            provider_box.prop(provider, "model")
            provider_box.prop(provider, "output_format")
            if provider.output_format == "json_schema":
                provider_box.label(text="本机地址示例：http://127.0.0.1:1234/v1")
            provider_box.prop(provider, "api_key")
            provider_box.prop(provider, "timeout_seconds")
            provider_box.label(
                text="Key 仅保留在本次会话，不写入 .blend",
                icon="LOCKED",
            )
            provider_box.label(text="也可使用 BSA_API_KEY / OPENAI_API_KEY")
            if provider.connection_status == "TESTING":
                provider_box.operator(
                    "bsa.cancel_provider_connection",
                    text="取消连接测试",
                    icon="CANCEL",
                )
            else:
                provider_box.operator(
                    "bsa.test_provider_connection",
                    text="测试连接",
                    icon="URL",
                )
            if provider.connection_message:
                _draw_wrapped(provider_box, provider.connection_message)
            if provider.credential_source:
                provider_box.label(text=f"凭据来源：{provider.credential_source}")
            if provider.connection_status == "SUCCESS":
                provider_box.label(text=f"连接耗时：{provider.latency_ms} ms")
                if provider.available_models_text:
                    _draw_wrapped(
                        provider_box,
                        f"部分可用模型：{provider.available_models_text}",
                    )
            provider_box.label(
                text="数据确认后才调用 AI；执行前请检查实际动作",
                icon="INFO",
            )

        input_box = layout.box()
        input_box.label(text="告诉我你想怎样调整场景", icon="OUTLINER_DATA_FONT")
        instruction_row = input_box.row()
        instruction_row.enabled = settings.assistant_status != AssistantStatus.PLANNING.value
        instruction_row.prop(settings, "instruction", text="")
        send_row = input_box.row()
        send_row.enabled = bool(settings.instruction.strip()) and (
            settings.assistant_status != AssistantStatus.PLANNING.value
        )
        send_row.operator("bsa.preview_instruction", text="解析要求", icon="PLAY")
        input_box.label(
            text="明确指令本地处理；AI 请求会先展示发送数据",
            icon="LOCKED",
        )
        input_box.label(text="示例：把 Lamp 放到 Desk 右侧")
        input_box.label(text="也可：Lamp 向左移动 20 厘米；锁定 Desk")

        if settings.assistant_status == AssistantStatus.AI_REVIEW.value:
            review_box = layout.box()
            review_box.label(text="发送给 AI 前确认", icon="VIEWZOOM")
            _draw_wrapped(review_box, provider.pending_data_preview, width=52)
            review_box.label(text="服务：OpenAI-compatible")
            review_box.label(text=f"模型：{provider.model or '尚未填写'}")
            review_box.label(text="输出格式：" + (
                "结构化 Schema" if provider.output_format == "json_schema" else "通用 JSON"
            ))
            review_box.label(text="API Key 不属于模型输入内容", icon="LOCKED")
            review_box.label(text="此时尚未联网，场景也没有修改", icon="INFO")
            review_actions = review_box.row(align=True)
            review_actions.operator(
                "bsa.start_ai_planning",
                text="同意并调用 AI",
                icon="CHECKMARK",
            )
            review_actions.operator(
                "bsa.discard_ai_request",
                text="不发送",
                icon="X",
            )

        if settings.assistant_status == AssistantStatus.PLANNING.value:
            planning_box = layout.box()
            planning_box.label(text="AI 正在生成结构化候选计划", icon="TIME")
            _draw_wrapped(planning_box, provider.planning_message)
            planning_box.label(text="等待期间场景不会被修改", icon="LOCKED")
            planning_box.operator(
                "bsa.cancel_ai_planning",
                text="取消 AI 规划",
                icon="CANCEL",
            )

        if settings.plan_json:
            preview_box = layout.box()
            preview_box.label(text="执行前确认", icon="PREVIEW_RANGE")
            _draw_wrapped(preview_box, settings.preview_text)
            preview_box.label(text="此时场景尚未修改", icon="INFO")
            if provider.last_plan_source == "llm":
                preview_box.label(
                    text=f"AI：{provider.last_provider} / {provider.last_model}",
                    icon="URL",
                )
                if provider.last_usage_available:
                    preview_box.label(
                        text=(
                            f"Token：输入 {provider.last_input_tokens} / "
                            f"输出 {provider.last_output_tokens}"
                        )
                    )
                preview_box.label(
                    text=(
                        f"请求 {provider.last_request_count} 次 · "
                        f"修复 {provider.last_repair_count} 次 · "
                        f"{provider.last_planning_latency_ms} ms"
                    )
                )
            action_row = preview_box.row(align=True)
            action_row.operator("bsa.confirm_plan", icon="CHECKMARK")
            action_row.operator("bsa.clear", text="放弃计划", icon="X")

        if settings.workflow_section == "PLACE":
            manual_box = layout.box()
            manual_box.prop(
                settings,
                "show_manual_controls",
                text="放到另一个物体表面",
                icon=(
                    "DISCLOSURE_TRI_DOWN"
                    if settings.show_manual_controls
                    else "DISCLOSURE_TRI_RIGHT"
                ),
                emboss=False,
            )
            if settings.show_manual_controls:
                manual_box.prop(settings, "source_object", text="移动物体")
                manual_box.prop(settings, "target_object", text="放到目标")
                manual_box.prop(settings, "region", text="摆放位置")
                manual_box.prop(settings, "clearance", text="表面间隙")
                manual_box.prop(settings, "lock_target")
                preview_row = manual_box.row()
                preview_row.enabled = selection_ready
                preview_row.operator(
                    "bsa.preview_plan",
                    text="按精确设置生成计划",
                    icon="PREVIEW_RANGE",
                )
                if source is not None and source == target:
                    warning = manual_box.row()
                    warning.alert = True
                    warning.label(text="两个选项不能是同一物体", icon="ERROR")

        if settings.result_text != "尚未执行操作" and settings.assistant_status not in {
            AssistantStatus.AI_REVIEW.value,
            AssistantStatus.PLANNING.value,
        }:
            result_box = layout.box()
            result_icon = (
                "CHECKMARK"
                if settings.assistant_status == AssistantStatus.SUCCESS.value
                else "INFO"
            )
            result_box.label(text=settings.result_text, icon=result_icon)
            if settings.result_detail:
                _draw_wrapped(result_box, settings.result_detail)
            if not settings.plan_json:
                result_box.operator("bsa.clear", text="开始下一项", icon="FILE_REFRESH")
