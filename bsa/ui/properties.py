"""Blender 界面状态：场景数据与会话秘密严格分离。"""

from __future__ import annotations

import bpy

from ..application.assistant_state import AssistantStatus


def _invalidate_preview(settings: object, context: object) -> None:
    """输入变化后立即废弃旧预览，避免执行与界面不一致的计划。"""

    if hasattr(settings, "assistant_status"):
        settings.assistant_status = AssistantStatus.IDLE.value
    if context is not None and hasattr(context.window_manager, "bsa_provider_session"):
        session = context.window_manager.bsa_provider_session
        session.pending_context_json = ""
        session.pending_data_preview = ""
    if settings.plan_json:
        settings.plan_json = ""
        settings.preview_text = "设置已改变，请重新生成预览"
        settings.result_text = "尚未执行新设置"
        settings.result_detail = "旧计划已自动失效"
        settings.result_json = ""


class BSASettings(bpy.types.PropertyGroup):
    """Scene-local M1 user input and preview state."""

    assistant_status: bpy.props.EnumProperty(
        name="助手状态",
        description="场景领航员当前所处的交互阶段",
        items=(
            ("IDLE", "待机", "等待用户输入"),
            ("AI_REVIEW", "等待数据确认", "等待确认发送给 AI 的最小数据"),
            ("PLANNING", "AI 正在规划", "正在等待结构化候选计划"),
            ("PLAN_READY", "等待确认", "计划已生成，等待用户确认"),
            ("WORKING", "正在工作", "正在通过安全执行层修改场景"),
            ("SUCCESS", "已完成", "修改已通过验证"),
            ("ERROR", "需要处理", "操作未完成"),
        ),
        default="IDLE",
    )
    show_avatar: bpy.props.BoolProperty(
        name="在视图中显示助手",
        description="在 3D 视图右下角显示可点击的场景领航员",
        default=True,
    )
    show_manual_controls: bpy.props.BoolProperty(
        name="显示精确控制",
        description="展开对象、区域和间隙等精确设置",
        default=False,
    )
    last_user_message: bpy.props.StringProperty(
        name="上一条用户消息",
        default="",
    )
    last_assistant_message: bpy.props.StringProperty(
        name="上一条助手消息",
        default="我已准备好。请告诉我你想怎样调整场景。",
    )

    instruction: bpy.props.StringProperty(
        name="中文指令",
        description="输入场景调整要求；明确指令本地处理，其他指令先显示 AI 发送数据",
        default="",
        maxlen=500,
        update=_invalidate_preview,
    )
    source_object: bpy.props.PointerProperty(
        name="要摆放的物体",
        description="选择需要移动的已有物体",
        type=bpy.types.Object,
        update=_invalidate_preview,
    )
    target_object: bpy.props.PointerProperty(
        name="目标表面",
        description="选择承载该物体的目标物体",
        type=bpy.types.Object,
        update=_invalidate_preview,
    )
    region: bpy.props.EnumProperty(
        name="摆放区域",
        description="选择物体在目标表面上的大致位置",
        items=(
            ("center", "中央", "放在目标中央"),
            ("left", "左侧", "放在世界坐标负 X 侧"),
            ("right", "右侧", "放在世界坐标正 X 侧"),
            ("front", "前侧", "放在世界坐标负 Y 侧"),
            ("back", "后侧", "放在世界坐标正 Y 侧"),
        ),
        default="right",
        update=_invalidate_preview,
    )
    clearance: bpy.props.FloatProperty(
        name="表面间隙",
        description="物体底部与目标顶面之间的距离；0 表示贴合表面",
        default=0.0,
        min=0.0,
        max=1000.0,
        unit="LENGTH",
        update=_invalidate_preview,
    )
    lock_target: bpy.props.BoolProperty(
        name="完成后锁定目标",
        description="执行成功后保护目标物体，避免后续操作意外移动它",
        default=True,
        update=_invalidate_preview,
    )
    plan_json: bpy.props.StringProperty(name="Plan JSON", default="")
    preview_text: bpy.props.StringProperty(name="预览", default="尚未生成计划")
    result_text: bpy.props.StringProperty(name="结果", default="尚未执行操作")
    result_detail: bpy.props.StringProperty(name="验证详情", default="")
    result_json: bpy.props.StringProperty(name="Result JSON", default="")


class BSAProviderSession(bpy.types.PropertyGroup):
    """只存在于当前 Blender 会话的 Provider 配置与连接结果。"""

    show_model_names: bpy.props.BoolProperty(
        name="可用模型名称",
        description="展开连接测试返回的模型名称；不触发联网",
        default=False,
        options={"SKIP_SAVE"},
    )
    show_settings: bpy.props.BoolProperty(
        name="设置",
        description="打开或收起 AI 服务、精确控制和助手显示设置",
        default=False,
        options={"SKIP_SAVE"},
    )
    show_data_details: bpy.props.BoolProperty(
        name="完整发送详情",
        description="查看本轮实际将发送的所有对象字段；不触发联网",
        default=False,
        options={"SKIP_SAVE"},
    )
    show_usage_details: bpy.props.BoolProperty(
        name="调用用量",
        description="展开最近一次 AI 规划的请求、Token 和耗时",
        default=False,
        options={"SKIP_SAVE"},
    )
    show_provider_settings: bpy.props.BoolProperty(
        name="AI 服务设置",
        description="展开用户自带 API 的连接设置",
        default=False,
        options={"SKIP_SAVE"},
    )
    provider_type: bpy.props.EnumProperty(
        name="服务类型",
        description="当前支持 OpenAI-compatible 的模型服务接口",
        items=(("OPENAI_COMPATIBLE", "OpenAI-compatible", "使用兼容的 /models 和 /chat/completions 接口"),),
        default="OPENAI_COMPATIBLE",
        options={"SKIP_SAVE"},
    )
    api_base: bpy.props.StringProperty(
        name="API 地址",
        description="服务的 API 根地址；远程地址必须使用 HTTPS",
        default="https://api.openai.com/v1",
        maxlen=2048,
        options={"SKIP_SAVE"},
    )
    output_format: bpy.props.EnumProperty(
        name="输出格式",
        description="LM Studio 选择结构化 Schema；其他服务按其兼容能力选择",
        items=(
            ("json_object", "通用 JSON", "保持既有兼容服务的 JSON 对象模式"),
            ("json_schema", "LM Studio 结构化输出", "发送严格候选 Schema，仍需本地校验和用户确认"),
        ),
        default="json_object",
        options={"SKIP_SAVE"},
    )
    model: bpy.props.StringProperty(
        name="模型",
        description="AI 规划必填；连接测试会检查模型是否在列表中",
        default="",
        maxlen=200,
        options={"SKIP_SAVE"},
    )
    api_key: bpy.props.StringProperty(
        name="API Key",
        description="只保留在本次 Blender 会话内，不写入 .blend 文件",
        default="",
        subtype="PASSWORD",
        options={"SKIP_SAVE"},
    )
    timeout_seconds: bpy.props.IntProperty(
        name="超时（秒）",
        description="连接测试或单次模型请求的最长等待时间",
        default=15,
        min=1,
        max=60,
        options={"SKIP_SAVE"},
    )
    connection_status: bpy.props.EnumProperty(
        name="连接状态",
        items=(
            ("NOT_TESTED", "未测试", "尚未测试连接"),
            ("TESTING", "测试中", "正在测试连接"),
            ("SUCCESS", "连接成功", "已验证服务连接"),
            ("ERROR", "连接失败", "连接测试失败"),
            ("CANCELED", "已取消", "连接测试已取消"),
        ),
        default="NOT_TESTED",
        options={"SKIP_SAVE"},
    )
    connection_message: bpy.props.StringProperty(
        name="连接说明",
        default="尚未测试连接",
        options={"SKIP_SAVE"},
    )
    credential_source: bpy.props.StringProperty(
        name="凭据来源",
        default="",
        options={"SKIP_SAVE"},
    )
    available_models_text: bpy.props.StringProperty(
        name="可用模型",
        default="",
        options={"SKIP_SAVE"},
    )
    latency_ms: bpy.props.IntProperty(
        name="连接耗时",
        default=0,
        min=0,
        options={"SKIP_SAVE"},
    )
    pending_context_json: bpy.props.StringProperty(
        name="待发送上下文",
        default="",
        options={"SKIP_SAVE"},
    )
    pending_data_preview: bpy.props.StringProperty(
        name="待发送数据说明",
        default="",
        options={"SKIP_SAVE"},
    )
    planning_message: bpy.props.StringProperty(
        name="AI 规划说明",
        default="",
        options={"SKIP_SAVE"},
    )
    last_plan_source: bpy.props.StringProperty(
        name="上次计划来源",
        default="",
        options={"SKIP_SAVE"},
    )
    last_provider: bpy.props.StringProperty(
        name="上次服务类型",
        default="",
        options={"SKIP_SAVE"},
    )
    last_model: bpy.props.StringProperty(
        name="上次模型",
        default="",
        options={"SKIP_SAVE"},
    )
    last_input_tokens: bpy.props.IntProperty(
        name="输入 Token",
        default=0,
        min=0,
        options={"SKIP_SAVE"},
    )
    last_output_tokens: bpy.props.IntProperty(
        name="输出 Token",
        default=0,
        min=0,
        options={"SKIP_SAVE"},
    )
    last_usage_available: bpy.props.BoolProperty(
        name="Token 用量可用",
        default=False,
        options={"SKIP_SAVE"},
    )
    last_planning_latency_ms: bpy.props.IntProperty(
        name="规划耗时",
        default=0,
        min=0,
        options={"SKIP_SAVE"},
    )
    last_request_count: bpy.props.IntProperty(
        name="模型请求次数",
        default=0,
        min=0,
        options={"SKIP_SAVE"},
    )
    last_repair_count: bpy.props.IntProperty(
        name="修复次数",
        default=0,
        min=0,
        options={"SKIP_SAVE"},
    )


def _invalidate_adapter_plate_review(settings: object, _context: object) -> None:
    """任何可执行参数变化都必须废弃旧摘要，避免确认过期设计。"""

    settings.stage = "INPUT"
    settings.review_fingerprint = ""
    settings.review_summary = ""
    settings.review_details = ""
    settings.review_notice = ""
    settings.error_message = ""
    settings.result_summary = ""
    settings.result_detail = ""
    settings.last_plan_id = ""
    settings.review_source = "manual"


def _invalidate_print_intent(settings: object, _context: object) -> None:
    """需求或回答变化后废弃尚未发送的 AI 请求。"""

    settings.ai_pending_json = ""
    settings.ai_data_preview = ""
    settings.ai_message = ""
    settings.stage = (
        "AI_NEEDS_INPUT" if settings.ai_previous_candidate_json else "START"
    )


class BSAAdapterPlateSettings(bpy.types.PropertyGroup):
    """保存在工程中的板件参数，以及只存在于会话中的检查/执行状态。"""

    stage: bpy.props.EnumProperty(
        name="创建阶段",
        items=(
            ("START", "描述需求", "描述用途，或直接填写完整尺寸"),
            ("AI_REVIEW", "确认发送", "检查本轮将发送给 AI 的最小数据"),
            ("AI_WORKING", "AI 正在分析", "等待严格零件候选"),
            ("AI_NEEDS_INPUT", "补充测量", "回答影响当前设计的关键问题"),
            ("AI_ERROR", "AI 未完成", "AI 请求或候选需要处理"),
            ("INPUT", "填写参数", "填写板件和孔位参数"),
            ("REVIEW", "检查设计", "检查本地展开后的设计摘要"),
            ("WORKING", "正在创建", "正在通过事务执行层创建并验证"),
            ("SUCCESS", "创建完成", "网格已创建并通过回读验证"),
            ("ERROR", "需要修改", "参数或执行结果需要处理"),
        ),
        default="START",
        options={"SKIP_SAVE"},
    )
    ai_instruction: bpy.props.StringProperty(
        name="你想做什么",
        description="描述零件用途、安装对象和已经知道的尺寸",
        default="",
        maxlen=1000,
        update=_invalidate_print_intent,
        options={"SKIP_SAVE"},
    )
    ai_answers: bpy.props.StringProperty(
        name="补充尺寸",
        description="回答上方测量问题；请注明毫米单位和对应对象",
        default="",
        maxlen=1000,
        update=_invalidate_print_intent,
        options={"SKIP_SAVE"},
    )
    show_ai_settings: bpy.props.BoolProperty(
        name="AI 服务设置",
        description="展开用户自带 API 的会话设置",
        default=False,
        options={"SKIP_SAVE"},
    )
    ai_pending_json: bpy.props.StringProperty(
        name="待发送零件需求", default="", options={"SKIP_SAVE"}
    )
    ai_data_preview: bpy.props.StringProperty(
        name="发送内容预览", default="", options={"SKIP_SAVE"}
    )
    ai_previous_candidate_json: bpy.props.StringProperty(
        name="上一轮零件候选", default="", options={"SKIP_SAVE"}
    )
    ai_questions_text: bpy.props.StringProperty(
        name="需要补充的测量", default="", options={"SKIP_SAVE"}
    )
    ai_message: bpy.props.StringProperty(
        name="AI 状态说明", default="", options={"SKIP_SAVE"}
    )
    review_source: bpy.props.StringProperty(
        name="设计来源", default="manual", options={"SKIP_SAVE"}
    )
    show_hole_settings: bpy.props.BoolProperty(
        name="孔位参数（4 个贯穿孔）",
        description="展开设备孔组和支架孔组的中心、孔距与孔径",
        default=False,
        options={"SKIP_SAVE"},
    )
    plate_id: bpy.props.StringProperty(
        name="零件编号",
        description="使用字母、数字、点、下划线或连字符；场景中不能重复",
        default="adapter-001",
        maxlen=128,
        update=_invalidate_adapter_plate_review,
    )
    width_mm: bpy.props.FloatProperty(
        name="板宽（mm）",
        default=80.0,
        min=0.01,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    depth_mm: bpy.props.FloatProperty(
        name="板深（mm）",
        default=40.0,
        min=0.01,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    thickness_mm: bpy.props.FloatProperty(
        name="厚度（mm）",
        default=3.0,
        min=0.01,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    corner_radius_mm: bpy.props.FloatProperty(
        name="圆角半径（mm）",
        default=2.0,
        min=0.0,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    device_center_x_mm: bpy.props.FloatProperty(
        name="中心 X（mm）",
        default=20.0,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    device_center_y_mm: bpy.props.FloatProperty(
        name="中心 Y（mm）",
        default=20.0,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    device_spacing_mm: bpy.props.FloatProperty(
        name="横向孔距（mm）",
        default=20.0,
        min=0.01,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    device_hole_diameter_mm: bpy.props.FloatProperty(
        name="孔径（mm）",
        default=3.2,
        min=0.01,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    support_center_x_mm: bpy.props.FloatProperty(
        name="中心 X（mm）",
        default=40.0,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    support_center_y_mm: bpy.props.FloatProperty(
        name="中心 Y（mm）",
        default=20.0,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    support_spacing_mm: bpy.props.FloatProperty(
        name="纵向孔距（mm）",
        default=20.0,
        min=0.01,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    support_hole_diameter_mm: bpy.props.FloatProperty(
        name="孔径（mm）",
        default=4.2,
        min=0.01,
        precision=2,
        update=_invalidate_adapter_plate_review,
    )
    review_fingerprint: bpy.props.StringProperty(
        name="检查指纹", default="", options={"SKIP_SAVE"}
    )
    review_summary: bpy.props.StringProperty(
        name="检查摘要", default="", options={"SKIP_SAVE"}
    )
    review_details: bpy.props.StringProperty(
        name="检查详情", default="", options={"SKIP_SAVE"}
    )
    review_notice: bpy.props.StringProperty(
        name="确认提示", default="", options={"SKIP_SAVE"}
    )
    error_message: bpy.props.StringProperty(
        name="错误说明", default="", options={"SKIP_SAVE"}
    )
    result_summary: bpy.props.StringProperty(
        name="执行结果", default="", options={"SKIP_SAVE"}
    )
    result_detail: bpy.props.StringProperty(
        name="验证详情", default="", options={"SKIP_SAVE"}
    )
    last_plan_id: bpy.props.StringProperty(
        name="最近计划 ID", default="", options={"SKIP_SAVE"}
    )
