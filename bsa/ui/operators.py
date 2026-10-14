"""Preview and confirm operators for the first deterministic product slice."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import bpy
from bpy.props import CollectionProperty, StringProperty
from bpy.types import OperatorFileListElement
from bpy_extras.io_utils import ExportHelper, ImportHelper

from ..application.assistant_state import (
    AssistantEvent,
    AssistantStatus,
    next_status,
)
from ..application.guided_workflow import GuidedWorkflowPlanBuilder
from ..application.plan_preview import describe_plan
from ..application.service import SceneEditingService
from ..blender_adapter.camera_controller import (
    apply_camera_frame_plan,
    render_camera_png,
)
from ..blender_adapter.ids import ensure_stable_ids, stable_id
from ..blender_adapter.model_importer import import_model_files
from ..blender_adapter.scene_port import BlenderScenePort
from ..core.camera_framing import (
    CameraFramePlan,
    build_camera_frame_plan,
    describe_camera_plan,
    validate_camera_plan_current,
)
from ..core.fingerprint import fingerprint_snapshot
from ..core.model_import import MODEL_FILE_FILTER
from ..core.validator import PlanValidator, relevant_object_ids
from ..domain.actions import (
    ActionPlan,
    LockAction,
    PlaceOnAction,
    PreserveTransformConstraint,
)
from ..domain.errors import DomainError, ErrorCode
from ..domain.scene import SceneSnapshot
from ..infra.credentials import CredentialSource, resolve_api_key
from ..infra.provider_process import ProviderWorkerTask, WorkerOutcome
from ..planner.context_builder import ContextBuilder
from ..planner.local_parser import LocalIntentParser
from ..planner.openai_compatible import (
    ProviderConnectionConfig,
    ProviderError,
    ProviderErrorCode,
)
from ..planner.plan_candidate import (
    PlanCandidate,
    build_action_plan,
    candidate_action_schema,
)
from ..planner.provider import PlannerRequest

_ERROR_MESSAGES = {
    ErrorCode.PLAN_SCHEMA_INVALID: (
        "计划格式无效",
        "请清空后重新生成预览",
    ),
    ErrorCode.PLAN_STALE: (
        "场景已改变，未执行",
        "请重新生成预览，再确认执行",
    ),
    ErrorCode.OBJECT_NOT_FOUND: (
        "找不到指令或预览中的物体",
        "请检查对象名称是否与 Blender 场景完全一致",
    ),
    ErrorCode.OBJECT_LOCKED: (
        "目标物体已被锁定",
        "请选择其他物体，或先明确解除锁定",
    ),
    ErrorCode.ACTION_NOT_SUPPORTED: (
        "当前版本不支持这项操作",
        "场景未被修改",
    ),
    ErrorCode.PRECONDITION_FAILED: (
        "操作条件不满足",
        "请检查对象状态、距离和目标表面",
    ),
    ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY: (
        "当前几何形状暂不支持",
        "目标需是水平且能用边界框可靠表示的表面",
    ),
    ErrorCode.POSTCONDITION_FAILED: (
        "结果验证失败，已自动回滚",
        "场景已恢复到执行前状态",
    ),
    ErrorCode.UNAUTHORIZED_CHANGE: (
        "检测到未授权的场景变化",
        "操作已取消并恢复场景",
    ),
    ErrorCode.ROLLBACK_FAILED: (
        "自动恢复验证失败",
        "请立即使用 Blender 撤销，并保存当前备份",
    ),
    ErrorCode.INTERNAL_ERROR: (
        "执行遇到内部错误",
        "场景未保留半执行结果；请记录操作步骤",
    ),
}

_PROVIDER_TASK: ProviderWorkerTask | None = None
_PROVIDER_TIMER_ACTIVE = False
_AI_TASK: ProviderWorkerTask | None = None
_AI_TIMER_ACTIVE = False
_AI_REVIEW_SNAPSHOT: SceneSnapshot | None = None
_AI_PLANNING_SNAPSHOT: SceneSnapshot | None = None

_PROVIDER_ERROR_MESSAGES = {
    ProviderErrorCode.INVALID_CONFIG.value: "请检查 API 地址、模型和超时设置",
    ProviderErrorCode.AUTHENTICATION_FAILED.value: "API Key 无效或没有访问权限",
    ProviderErrorCode.RATE_LIMITED.value: "请求过于频繁或账户额度受限",
    ProviderErrorCode.CONNECTION_FAILED.value: (
        "无法连接模型服务，请检查地址和网络"
    ),
    ProviderErrorCode.TIMEOUT.value: "连接模型服务超时",
    ProviderErrorCode.INVALID_RESPONSE.value: "服务返回的模型列表不兼容",
    ProviderErrorCode.SERVER_ERROR.value: "模型服务暂时不可用",
    ProviderErrorCode.ONLINE_ACCESS_DISABLED.value: "Blender 当前禁止扩展联网",
    ProviderErrorCode.CANCELED.value: "连接测试已取消",
    ProviderErrorCode.WORKER_FAILED.value: "连接测试进程未能正常完成",
    ProviderErrorCode.OUTPUT_INVALID.value: "模型没有返回可用的结构化计划",
}

_CREDENTIAL_SOURCE_LABELS = {
    CredentialSource.SESSION: "本次会话输入",
    CredentialSource.BSA_ENV: "环境变量 BSA_API_KEY",
    CredentialSource.OPENAI_ENV: "环境变量 OPENAI_API_KEY",
    CredentialSource.NONE: "未提供",
}


def _friendly_error(code: ErrorCode) -> tuple[str, str]:
    """将稳定错误码转换为面向用户的中文说明。"""

    return _ERROR_MESSAGES.get(code, ("操作未完成", "场景保持原状"))


def _transition(settings: object, event: AssistantEvent) -> None:
    """通过纯状态机更新 Blender 属性，避免界面状态与执行阶段脱节。"""

    current = AssistantStatus(settings.assistant_status)
    settings.assistant_status = next_status(current, event).value


def _store_preview(settings: object, plan: ActionPlan, snapshot: SceneSnapshot) -> None:
    """将已构建的计划存入界面，不修改场景物体。"""

    settings.plan_json = json.dumps(plan.to_dict(), ensure_ascii=False)
    settings.preview_text = describe_plan(plan, snapshot)
    settings.result_text = "等待确认，场景尚未修改"
    settings.result_detail = "请检查计划内容，确认无误后再执行"
    settings.result_json = ""
    settings.last_assistant_message = plan.user_summary
    _transition(settings, AssistantEvent.PREVIEW_READY)


def _set_domain_failure(settings: object, error: DomainError) -> None:
    """Show one structured domain error without losing its recovery boundary."""

    settings.result_text, settings.result_detail = _friendly_error(error.code)
    if error.message:
        settings.result_detail = error.message
    settings.last_assistant_message = f"{settings.result_text}。{settings.result_detail}"
    _transition(settings, AssistantEvent.FAILED)


def _selected_object_ids(context: object, *, mesh_only: bool = False) -> tuple[str, ...]:
    """Return stable IDs in a deterministic order for current Blender selection."""

    selected = tuple(
        obj
        for obj in context.selected_objects
        if not mesh_only or obj.type == "MESH"
    )
    if not selected:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "请先在视图中选择模型")
    ensure_stable_ids(selected)
    return tuple(
        stable_id(obj)
        for obj in sorted(selected, key=lambda item: (item.name.casefold(), item.name))
    )


def _store_guided_preview(context: object, plan: ActionPlan) -> None:
    snapshot = BlenderScenePort(context.scene).read_snapshot()
    _store_preview(context.scene.bsa_settings, plan, snapshot)
    context.window_manager.bsa_provider_session.last_plan_source = "ui"


def _set_provider_error(session: object, code: str, fallback: str = "") -> None:
    """只把稳定、安全的中文错误写入 UI。"""

    session.connection_status = (
        "CANCELED" if code == ProviderErrorCode.CANCELED.value else "ERROR"
    )
    session.connection_message = _PROVIDER_ERROR_MESSAGES.get(
        code,
        fallback or "连接测试失败",
    )
    session.available_models_text = ""
    session.latency_ms = 0


def _apply_provider_outcome(session: object, outcome: WorkerOutcome) -> None:
    """把无秘密的工作进程结果转换成会话显示状态。"""

    if not outcome.ok:
        code = str(outcome.error.get("code", ProviderErrorCode.WORKER_FAILED.value))
        _set_provider_error(session, code)
        return

    models = outcome.result.get("models", [])
    if not isinstance(models, list) or not all(isinstance(item, str) for item in models):
        _set_provider_error(session, ProviderErrorCode.WORKER_FAILED.value)
        return
    session.connection_status = "SUCCESS"
    session.latency_ms = max(0, int(outcome.result.get("latency_ms", 0)))
    session.available_models_text = "、".join(models[:8])
    model_available = outcome.result.get("model_available")
    if model_available is False:
        session.connection_message = (
            f"服务可连接，共发现 {len(models)} 个模型；"
            "填写的模型不在返回列表中"
        )
    elif model_available is True:
        session.connection_message = (
            f"连接成功，模型可用；共发现 {len(models)} 个模型"
        )
    else:
        session.connection_message = f"连接成功，共发现 {len(models)} 个模型"


def _poll_provider_task() -> float | None:
    """由 Blender 主线程定时器非阻塞轮询 Provider 子进程。"""

    global _PROVIDER_TASK, _PROVIDER_TIMER_ACTIVE
    if not _PROVIDER_TIMER_ACTIVE or _PROVIDER_TASK is None:
        _PROVIDER_TIMER_ACTIVE = False
        return None
    try:
        outcome = _PROVIDER_TASK.poll()
        if outcome is None:
            return 0.1
        if hasattr(bpy.types.WindowManager, "bsa_provider_session"):
            _apply_provider_outcome(
                bpy.context.window_manager.bsa_provider_session,
                outcome,
            )
    except Exception:
        if hasattr(bpy.types.WindowManager, "bsa_provider_session"):
            _set_provider_error(
                bpy.context.window_manager.bsa_provider_session,
                ProviderErrorCode.WORKER_FAILED.value,
            )
        if _PROVIDER_TASK is not None:
            try:
                _PROVIDER_TASK.cancel()
            except Exception:
                pass
        _PROVIDER_TASK = None
        _PROVIDER_TIMER_ACTIVE = False
    finally:
        if "outcome" in locals() and outcome is not None:
            _PROVIDER_TASK = None
            _PROVIDER_TIMER_ACTIVE = False
    return None


def _clear_pending_ai(session: object) -> None:
    """清除尚未发送的会话上下文，不触碰场景数据。"""

    session.pending_context_json = ""
    session.pending_data_preview = ""


def _set_ai_failure(
    settings: object,
    session: object,
    message: str,
    detail: str = "场景没有被 AI 规划流程修改",
) -> None:
    settings.plan_json = ""
    settings.result_json = ""
    settings.result_text = message
    settings.result_detail = detail
    settings.last_assistant_message = f"{message}。{detail}"
    session.planning_message = message
    _transition(settings, AssistantEvent.FAILED)


def _store_ai_usage(session: object, result: dict[str, object]) -> None:
    usage = result.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("AI usage result is invalid")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    session.last_provider = str(usage.get("provider", ""))
    session.last_model = str(usage.get("model", ""))
    session.last_usage_available = isinstance(input_tokens, int) and isinstance(
        output_tokens, int
    )
    session.last_input_tokens = input_tokens if isinstance(input_tokens, int) else 0
    session.last_output_tokens = output_tokens if isinstance(output_tokens, int) else 0
    latency = usage.get("latency_ms")
    session.last_planning_latency_ms = latency if isinstance(latency, int) else 0
    request_count = result.get("request_count")
    repair_count = result.get("repair_count")
    session.last_request_count = request_count if isinstance(request_count, int) else 0
    session.last_repair_count = repair_count if isinstance(repair_count, int) else 0
    session.last_plan_source = "llm"


def _apply_ai_outcome(
    settings: object,
    session: object,
    outcome: WorkerOutcome,
) -> None:
    """在 Blender 主线程二次校验候选计划并生成只读预览。"""

    global _AI_PLANNING_SNAPSHOT
    if not outcome.ok:
        code = str(outcome.error.get("code", ProviderErrorCode.WORKER_FAILED.value))
        message = _PROVIDER_ERROR_MESSAGES.get(code, "AI 规划失败")
        if code == ProviderErrorCode.CANCELED.value:
            message = "AI 规划已取消"
        _set_ai_failure(settings, session, message)
        return
    if _AI_PLANNING_SNAPSHOT is None:
        _set_ai_failure(settings, session, "找不到规划开始时的场景快照")
        return
    plan_payload = outcome.result.get("plan_payload")
    try:
        pending = json.loads(session.pending_context_json)
        scene_context = pending["scene_context"]
        allowed_ids = {
            item["object_id"]
            for item in scene_context["objects"]
            if isinstance(item, dict) and isinstance(item.get("object_id"), str)
        }
        if not isinstance(plan_payload, dict):
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "AI candidate is missing")
        candidate = PlanCandidate.from_dict(
            plan_payload,
            allowed_object_ids=allowed_ids,
        )
        plan = build_action_plan(candidate, _AI_PLANNING_SNAPSHOT)
        current_snapshot = BlenderScenePort(bpy.context.scene).read_snapshot()
        PlanValidator().validate(plan, current_snapshot)
        _store_ai_usage(session, outcome.result)
        _store_preview(settings, plan, current_snapshot)
        session.planning_message = "AI 候选计划已通过本地校验，等待你的确认"
        _clear_pending_ai(session)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, DomainError) as error:
        if isinstance(error, DomainError):
            message, detail = _friendly_error(error.code)
        else:
            message = "AI 计划格式无效"
            detail = "候选计划未进入执行层，场景保持原状"
        _set_ai_failure(settings, session, message, detail)
        _clear_pending_ai(session)


def _poll_ai_task() -> float | None:
    """非阻塞轮询 AI 规划子进程；只在主线程构造计划预览。"""

    global _AI_TASK, _AI_TIMER_ACTIVE, _AI_PLANNING_SNAPSHOT
    if not _AI_TIMER_ACTIVE or _AI_TASK is None:
        _AI_TIMER_ACTIVE = False
        return None
    outcome: WorkerOutcome | None = None
    try:
        outcome = _AI_TASK.poll()
        if outcome is None:
            return 0.1
        if hasattr(bpy.types.WindowManager, "bsa_provider_session"):
            _apply_ai_outcome(
                bpy.context.scene.bsa_settings,
                bpy.context.window_manager.bsa_provider_session,
                outcome,
            )
    except Exception:
        if hasattr(bpy.types.WindowManager, "bsa_provider_session"):
            _set_ai_failure(
                bpy.context.scene.bsa_settings,
                bpy.context.window_manager.bsa_provider_session,
                "AI 规划进程未能正常完成",
            )
        if _AI_TASK is not None:
            try:
                _AI_TASK.cancel()
            except Exception:
                pass
        _AI_TASK = None
        _AI_TIMER_ACTIVE = False
        _AI_PLANNING_SNAPSHOT = None
    finally:
        if outcome is not None:
            _AI_TASK = None
            _AI_TIMER_ACTIVE = False
            _AI_PLANNING_SNAPSHOT = None
    return None


def cancel_provider_task() -> None:
    """在扩展卸载时关闭仍在运行的连接或规划任务。"""

    global _PROVIDER_TASK, _PROVIDER_TIMER_ACTIVE
    global _AI_TASK, _AI_TIMER_ACTIVE, _AI_REVIEW_SNAPSHOT, _AI_PLANNING_SNAPSHOT
    if _PROVIDER_TASK is not None:
        _PROVIDER_TASK.cancel()
    _PROVIDER_TASK = None
    _PROVIDER_TIMER_ACTIVE = False
    if _AI_TASK is not None:
        _AI_TASK.cancel()
    _AI_TASK = None
    _AI_TIMER_ACTIVE = False
    _AI_REVIEW_SNAPSHOT = None
    _AI_PLANNING_SNAPSHOT = None


class BSA_OT_test_provider_connection(bpy.types.Operator):
    """在隔离子进程中测试 OpenAI-compatible `/models` 连接。"""

    bl_idname = "bsa.test_provider_connection"
    bl_label = "测试连接"
    bl_description = "只请求模型列表，不发送场景、指令或物体数据"

    def execute(self, context: object) -> set[str]:
        global _PROVIDER_TASK, _PROVIDER_TIMER_ACTIVE
        session = context.window_manager.bsa_provider_session
        if _AI_TASK is not None:
            session.connection_message = "请先完成或取消当前 AI 规划"
            self.report({"WARNING"}, session.connection_message)
            return {"CANCELLED"}
        try:
            config = ProviderConnectionConfig(
                api_base=session.api_base,
                model=session.model,
                timeout_seconds=session.timeout_seconds,
                output_format=session.output_format,
            ).validated()
        except ProviderError as error:
            _set_provider_error(session, error.code.value, error.message)
            self.report({"WARNING"}, session.connection_message)
            return {"CANCELLED"}

        if not getattr(bpy.app, "online_access", True):
            _set_provider_error(session, ProviderErrorCode.ONLINE_ACCESS_DISABLED.value)
            self.report({"WARNING"}, session.connection_message)
            return {"CANCELLED"}

        credential = resolve_api_key(session.api_key)
        host = (urlsplit(config.api_base).hostname or "").lower()
        if not credential.value and host not in {"localhost", "127.0.0.1", "::1"}:
            _set_provider_error(
                session,
                ProviderErrorCode.INVALID_CONFIG.value,
                "远程服务需要 API Key",
            )
            session.connection_message = "请填写 API Key，或设置 BSA_API_KEY 环境变量"
            self.report({"WARNING"}, session.connection_message)
            return {"CANCELLED"}

        if _PROVIDER_TASK is not None:
            _PROVIDER_TASK.cancel()
        try:
            _PROVIDER_TASK = ProviderWorkerTask.start(config, credential.value)
        except ProviderError as error:
            _set_provider_error(session, error.code.value, error.message)
            self.report({"WARNING"}, session.connection_message)
            return {"CANCELLED"}

        session.connection_status = "TESTING"
        session.connection_message = "正在安全测试连接；不会发送场景或指令"
        session.credential_source = _CREDENTIAL_SOURCE_LABELS[credential.source]
        session.available_models_text = ""
        session.latency_ms = 0
        _PROVIDER_TIMER_ACTIVE = True
        bpy.app.timers.register(_poll_provider_task, first_interval=0.1)
        return {"FINISHED"}


class BSA_OT_cancel_provider_connection(bpy.types.Operator):
    """取消正在运行的 Provider 连接测试。"""

    bl_idname = "bsa.cancel_provider_connection"
    bl_label = "取消连接测试"
    bl_description = "停止当前连接测试"

    def execute(self, context: object) -> set[str]:
        global _PROVIDER_TASK, _PROVIDER_TIMER_ACTIVE
        if _PROVIDER_TASK is None:
            return {"CANCELLED"}
        outcome = _PROVIDER_TASK.cancel()
        _apply_provider_outcome(context.window_manager.bsa_provider_session, outcome)
        _PROVIDER_TASK = None
        _PROVIDER_TIMER_ACTIVE = False
        return {"FINISHED"}


class BSA_OT_start_ai_planning(bpy.types.Operator):
    """用户审查数据后，启动隔离的结构化 AI 规划。"""

    bl_idname = "bsa.start_ai_planning"
    bl_label = "同意并调用 AI"
    bl_description = (
        "发送界面中列出的最小数据，生成候选计划；不会直接修改场景"
    )

    def execute(self, context: object) -> set[str]:
        global _AI_TASK, _AI_TIMER_ACTIVE, _AI_REVIEW_SNAPSHOT, _AI_PLANNING_SNAPSHOT
        settings = context.scene.bsa_settings
        session = context.window_manager.bsa_provider_session
        if settings.assistant_status != AssistantStatus.AI_REVIEW.value:
            self.report({"WARNING"}, "请先生成并检查本轮发送数据")
            return {"CANCELLED"}
        if not session.pending_context_json or _AI_REVIEW_SNAPSHOT is None:
            _set_ai_failure(settings, session, "待发送数据已经失效")
            return {"CANCELLED"}
        if _PROVIDER_TASK is not None or _AI_TASK is not None:
            self.report({"WARNING"}, "已有 Provider 任务正在运行")
            return {"CANCELLED"}
        try:
            config = ProviderConnectionConfig(
                api_base=session.api_base,
                model=session.model,
                timeout_seconds=session.timeout_seconds,
                output_format=session.output_format,
            ).validated_for_planning()
            pending = json.loads(session.pending_context_json)
            scene_context = pending["scene_context"]
            action_schema = pending["action_schema"]
            instruction = pending["instruction"]
            if not isinstance(scene_context, dict) or not isinstance(action_schema, dict):
                raise ValueError("pending AI context is invalid")
            if not isinstance(instruction, str) or instruction != settings.instruction.strip():
                raise ValueError("instruction changed after data review")
            object_ids = tuple(
                item["object_id"]
                for item in scene_context.get("objects", [])
                if isinstance(item, dict) and isinstance(item.get("object_id"), str)
            )
            current_snapshot = BlenderScenePort(context.scene).read_snapshot()
            if fingerprint_snapshot(
                _AI_REVIEW_SNAPSHOT, object_ids
            ) != fingerprint_snapshot(current_snapshot, object_ids):
                raise DomainError(
                    ErrorCode.PLAN_STALE,
                    "Scene changed after AI data review",
                )
            request = PlannerRequest(
                instruction=instruction,
                scene_context=scene_context,
                action_schema=action_schema,
            )
        except DomainError as error:
            message, detail = _friendly_error(error.code)
            _set_ai_failure(settings, session, message, detail)
            _clear_pending_ai(session)
            return {"CANCELLED"}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            _set_ai_failure(settings, session, "待发送数据格式无效")
            _clear_pending_ai(session)
            return {"CANCELLED"}
        except ProviderError as error:
            message = _PROVIDER_ERROR_MESSAGES.get(error.code.value, error.message)
            _set_ai_failure(settings, session, message)
            return {"CANCELLED"}

        if not getattr(bpy.app, "online_access", True):
            _set_ai_failure(settings, session, "Blender 当前禁止扩展联网")
            return {"CANCELLED"}
        credential = resolve_api_key(session.api_key)
        host = (urlsplit(config.api_base).hostname or "").lower()
        if not credential.value and host not in {"localhost", "127.0.0.1", "::1"}:
            _set_ai_failure(
                settings,
                session,
                "请填写 API Key，或设置 BSA_API_KEY 环境变量",
            )
            return {"CANCELLED"}
        try:
            _AI_TASK = ProviderWorkerTask.start_plan(config, credential.value, request)
        except ProviderError as error:
            message = _PROVIDER_ERROR_MESSAGES.get(error.code.value, error.message)
            _set_ai_failure(settings, session, message)
            return {"CANCELLED"}

        _AI_PLANNING_SNAPSHOT = _AI_REVIEW_SNAPSHOT
        _AI_REVIEW_SNAPSHOT = None
        _AI_TIMER_ACTIVE = True
        session.credential_source = _CREDENTIAL_SOURCE_LABELS[credential.source]
        session.planning_message = "正在等待结构化候选计划；场景尚未修改"
        _transition(settings, AssistantEvent.AI_PLANNING_STARTED)
        settings.last_assistant_message = session.planning_message
        bpy.app.timers.register(_poll_ai_task, first_interval=0.1)
        return {"FINISHED"}


class BSA_OT_cancel_ai_planning(bpy.types.Operator):
    """取消 AI 规划子进程，不创建计划。"""

    bl_idname = "bsa.cancel_ai_planning"
    bl_label = "取消 AI 规划"
    bl_description = "停止模型请求；场景不会被修改"

    def execute(self, context: object) -> set[str]:
        global _AI_TASK, _AI_TIMER_ACTIVE, _AI_PLANNING_SNAPSHOT
        if _AI_TASK is None:
            return {"CANCELLED"}
        outcome = _AI_TASK.cancel()
        _apply_ai_outcome(
            context.scene.bsa_settings,
            context.window_manager.bsa_provider_session,
            outcome,
        )
        _AI_TASK = None
        _AI_TIMER_ACTIVE = False
        _AI_PLANNING_SNAPSHOT = None
        _clear_pending_ai(context.window_manager.bsa_provider_session)
        return {"FINISHED"}


class BSA_OT_discard_ai_request(bpy.types.Operator):
    """放弃尚未发送的 AI 请求。"""

    bl_idname = "bsa.discard_ai_request"
    bl_label = "不发送"
    bl_description = "清除本轮待发送数据，不访问网络"

    def execute(self, context: object) -> set[str]:
        global _AI_REVIEW_SNAPSHOT
        session = context.window_manager.bsa_provider_session
        settings = context.scene.bsa_settings
        _clear_pending_ai(session)
        _AI_REVIEW_SNAPSHOT = None
        settings.plan_json = ""
        settings.result_text = "尚未执行操作"
        settings.result_detail = ""
        settings.last_assistant_message = "已取消发送，本轮没有调用 AI。"
        _transition(settings, AssistantEvent.CLEARED)
        return {"FINISHED"}


class BSA_OT_open_assistant(bpy.types.Operator):
    """Open the assistant as a compact popover next to the 3D view."""

    bl_idname = "bsa.open_assistant"
    bl_label = "打开场景领航员"
    bl_description = "打开场景领航员的中文指令面板"

    def invoke(self, context: object, _event: object) -> set[str]:
        return context.window_manager.invoke_popup(self, width=560)

    def draw(self, context: object) -> None:
        # 延迟导入避免注册阶段的模块环；Panel 与弹窗复用完全相同的界面。
        from .panel import BSA_PT_scene_assistant

        BSA_PT_scene_assistant.draw(self, context)

    def execute(self, _context: object) -> set[str]:
        return {"FINISHED"}


class BSA_OT_launch_assistant(bpy.types.Operator):
    """Bridge Gizmo execution to the popup operator's invoke path."""

    bl_idname = "bsa.launch_assistant"
    bl_label = "启动场景领航员"
    bl_description = "从视图助手形象打开中文指令面板"

    def execute(self, _context: object) -> set[str]:
        result = bpy.ops.bsa.open_assistant("INVOKE_DEFAULT")
        if result != {"RUNNING_MODAL"}:
            self.report({"ERROR"}, "无法打开场景领航员")
            return {"CANCELLED"}
        return {"FINISHED"}


class BSA_OT_import_models(bpy.types.Operator, ImportHelper):
    """Import one or more existing model files as a recoverable batch."""

    bl_idname = "bsa.import_models"
    bl_label = "导入模型文件"
    bl_description = "导入 BLEND、FBX、OBJ、GLB/GLTF、STL 或 PLY，并选中新模型"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: StringProperty(default=MODEL_FILE_FILTER, options={"HIDDEN"})
    files: CollectionProperty(type=OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_settings
        paths = tuple(Path(self.directory) / item.name for item in self.files)
        if not paths and self.filepath:
            paths = (Path(self.filepath),)
        try:
            result = import_model_files(context, paths)
        except DomainError as error:
            _set_domain_failure(settings, error)
            self.report({"ERROR"}, settings.result_detail)
            return {"CANCELLED"}
        settings.workflow_section = "PLACE"
        settings.result_text = f"已导入 {len(result.files)} 个文件"
        settings.result_detail = f"新增 {len(result.object_names)} 个物体，已全部选中"
        settings.last_assistant_message = (
            "模型已经导入。下一步可以先点击“落到地面”，再排列或调整大小。"
        )
        settings.plan_json = ""
        _transition(settings, AssistantEvent.CLEARED)
        self.report({"INFO"}, settings.result_text)
        return {"FINISHED"}


class BSA_OT_preview_ground(bpy.types.Operator):
    bl_idname = "bsa.preview_ground"
    bl_label = "预览落到地面"
    bl_description = "计算所选模型落到世界坐标 Z=0 的动作，确认后才执行"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_settings
        try:
            port = BlenderScenePort(context.scene)
            snapshot = port.read_snapshot()
            plan = GuidedWorkflowPlanBuilder().ground(
                snapshot,
                _selected_object_ids(context, mesh_only=True),
            )
            _store_guided_preview(context, plan)
            return {"FINISHED"}
        except DomainError as error:
            _set_domain_failure(settings, error)
            self.report({"WARNING"}, settings.result_detail)
            return {"CANCELLED"}


class BSA_OT_preview_align(bpy.types.Operator):
    bl_idname = "bsa.preview_align"
    bl_label = "预览对齐"
    bl_description = "以活动物体为基准，对齐其他所选模型；确认后才执行"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_settings
        try:
            snapshot = BlenderScenePort(context.scene).read_snapshot()
            object_ids = _selected_object_ids(context, mesh_only=True)
            reference = context.view_layer.objects.active
            if reference is None or reference.type != "MESH" or not reference.select_get():
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "请让一个所选模型保持为活动物体，作为对齐基准",
                )
            ensure_stable_ids((reference,))
            plan = GuidedWorkflowPlanBuilder().align(
                snapshot,
                object_ids,
                reference_id=stable_id(reference),
                axis=settings.layout_axis,
                anchor=settings.align_anchor,
            )
            _store_guided_preview(context, plan)
            return {"FINISHED"}
        except DomainError as error:
            _set_domain_failure(settings, error)
            self.report({"WARNING"}, settings.result_detail)
            return {"CANCELLED"}


class BSA_OT_preview_grid(bpy.types.Operator):
    bl_idname = "bsa.preview_grid"
    bl_label = "预览网格排列"
    bl_description = "按模型最大尺寸与指定间隙生成网格动作，确认后才执行"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_settings
        try:
            snapshot = BlenderScenePort(context.scene).read_snapshot()
            plan = GuidedWorkflowPlanBuilder().grid(
                snapshot,
                _selected_object_ids(context, mesh_only=True),
                columns=settings.grid_columns,
                gap=settings.layout_gap,
            )
            _store_guided_preview(context, plan)
            return {"FINISHED"}
        except DomainError as error:
            _set_domain_failure(settings, error)
            self.report({"WARNING"}, settings.result_detail)
            return {"CANCELLED"}


class BSA_OT_preview_rotate(bpy.types.Operator):
    bl_idname = "bsa.preview_rotate"
    bl_label = "预览旋转"
    bl_description = "为所选模型生成本地轴旋转计划，确认后才执行"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_settings
        try:
            snapshot = BlenderScenePort(context.scene).read_snapshot()
            plan = GuidedWorkflowPlanBuilder().rotate(
                snapshot,
                _selected_object_ids(context, mesh_only=True),
                axis=settings.rotation_axis,
                angle_degrees=settings.rotation_degrees,
            )
            _store_guided_preview(context, plan)
            return {"FINISHED"}
        except DomainError as error:
            _set_domain_failure(settings, error)
            self.report({"WARNING"}, settings.result_detail)
            return {"CANCELLED"}


class BSA_OT_preview_scale(bpy.types.Operator):
    bl_idname = "bsa.preview_scale"
    bl_label = "预览等比缩放"
    bl_description = "为所选模型生成等比缩放计划，确认后才执行"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_settings
        try:
            snapshot = BlenderScenePort(context.scene).read_snapshot()
            plan = GuidedWorkflowPlanBuilder().scale(
                snapshot,
                _selected_object_ids(context, mesh_only=True),
                factor=settings.scale_factor,
            )
            _store_guided_preview(context, plan)
            return {"FINISHED"}
        except DomainError as error:
            _set_domain_failure(settings, error)
            self.report({"WARNING"}, settings.result_detail)
            return {"CANCELLED"}


class BSA_OT_preview_camera(bpy.types.Operator):
    bl_idname = "bsa.preview_camera"
    bl_label = "生成取景预览"
    bl_description = "根据物体边界计算相机位置；此时不会创建或移动相机"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_settings
        try:
            snapshot = BlenderScenePort(context.scene).read_snapshot()
            if settings.camera_scope == "SELECTED":
                object_ids = _selected_object_ids(context, mesh_only=True)
            else:
                object_ids = tuple(
                    obj.object_id
                    for obj in snapshot.objects
                    if obj.object_type == "MESH" and obj.visible
                )
            plan = build_camera_frame_plan(
                snapshot,
                object_ids,
                lens_mm=settings.camera_lens_mm,
                aspect_ratio=settings.render_width / settings.render_height,
                margin=settings.camera_margin,
            )
            settings.camera_plan_json = json.dumps(plan.to_dict(), ensure_ascii=False)
            settings.camera_preview_text = describe_camera_plan(plan, snapshot)
            settings.result_text = "取景计划已生成，场景尚未修改"
            settings.result_detail = "检查焦距、留白和取景对象后再确认"
            return {"FINISHED"}
        except DomainError as error:
            settings.camera_plan_json = ""
            _set_domain_failure(settings, error)
            self.report({"WARNING"}, settings.result_detail)
            return {"CANCELLED"}


class BSA_OT_confirm_camera(bpy.types.Operator):
    bl_idname = "bsa.confirm_camera"
    bl_label = "确认并应用相机"
    bl_description = "重新检查取景对象后创建或移动场景相机"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_settings
        if not settings.camera_plan_json:
            self.report({"WARNING"}, "请先生成取景预览")
            return {"CANCELLED"}
        try:
            payload = json.loads(settings.camera_plan_json)
            if not isinstance(payload, dict):
                raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "取景计划格式无效")
            plan = CameraFramePlan.from_dict(payload)
            snapshot = BlenderScenePort(context.scene).read_snapshot()
            validate_camera_plan_current(plan, snapshot)
            apply_camera_frame_plan(context.scene, plan)
        except (json.JSONDecodeError, DomainError) as error:
            domain_error = (
                error
                if isinstance(error, DomainError)
                else DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "取景计划格式无效")
            )
            settings.camera_plan_json = ""
            _set_domain_failure(settings, domain_error)
            self.report({"ERROR"}, settings.result_detail)
            return {"CANCELLED"}
        settings.camera_plan_json = ""
        settings.camera_preview_text = "相机已应用；可以导出 PNG"
        settings.result_text = "相机已创建或更新"
        settings.result_detail = "目标模型已通过确定性边界取景检查"
        settings.last_assistant_message = (
            "取景完成。现在可以导出一张 PNG 检查效果。"
        )
        self.report({"INFO"}, settings.result_text)
        return {"FINISHED"}


class BSA_OT_export_png(bpy.types.Operator, ExportHelper):
    bl_idname = "bsa.export_png"
    bl_label = "导出 PNG"
    bl_description = "使用当前场景相机渲染 PNG，并恢复原有渲染设置"

    filename_ext = ".png"
    filter_glob: StringProperty(default="*.png", options={"HIDDEN"})

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_settings
        try:
            output = render_camera_png(
                context.scene,
                self.filepath,
                resolution_x=settings.render_width,
                resolution_y=settings.render_height,
                transparent=settings.render_transparent,
            )
        except DomainError as error:
            _set_domain_failure(settings, error)
            self.report({"ERROR"}, settings.result_detail)
            return {"CANCELLED"}
        settings.result_text = "PNG 已导出"
        settings.result_detail = str(output)
        settings.last_assistant_message = f"图片已经导出到 {output.name}。"
        self.report({"INFO"}, settings.result_text)
        return {"FINISHED"}


class BSA_OT_preview_instruction(bpy.types.Operator):
    """本地优先；无法可靠解析时先生成 AI 数据预览。"""

    bl_idname = "bsa.preview_instruction"
    bl_label = "解析并生成预览"
    bl_description = "明确指令本地解析；其他指令先展示将发送给 AI 的数据"

    def execute(self, context: object) -> set[str]:
        global _AI_REVIEW_SNAPSHOT
        settings = context.scene.bsa_settings
        session = context.window_manager.bsa_provider_session
        if _AI_TASK is not None:
            self.report({"WARNING"}, "AI 正在规划，请先等待或取消")
            return {"CANCELLED"}
        _clear_pending_ai(session)
        _AI_REVIEW_SNAPSHOT = None
        settings.plan_json = ""
        settings.last_user_message = settings.instruction.strip()
        try:
            port = BlenderScenePort(context.scene)
            snapshot = port.read_snapshot()
            plan = LocalIntentParser().parse(settings.instruction, snapshot)
            placement = next(
                (
                    action
                    for action in plan.actions
                    if isinstance(action, PlaceOnAction)
                ),
                None,
            )
            if placement is not None:
                objects_by_id = {
                    stable_id(obj): obj for obj in context.scene.objects
                }
                source = objects_by_id.get(placement.object_id)
                target = objects_by_id.get(placement.target_id)
                if source is None or target is None:
                    raise DomainError(
                        ErrorCode.OBJECT_NOT_FOUND,
                        "Parsed object disappeared before preview",
                    )

                # 先同步手动字段，最后再写入计划，避免 update 回调清除预览。
                settings.source_object = source
                settings.target_object = target
                settings.region = placement.region
                settings.clearance = placement.clearance
                settings.lock_target = any(
                    isinstance(action, LockAction) for action in plan.actions
                )
            _store_preview(settings, plan, snapshot)
            session.last_plan_source = "local_parser"
            return {"FINISHED"}
        except DomainError as error:
            if error.code == ErrorCode.ACTION_NOT_SUPPORTED:
                try:
                    built = ContextBuilder().build(settings.instruction, snapshot)
                except ValueError:
                    built = None
                if built is not None:
                    pending = {
                        "instruction": settings.instruction.strip(),
                        "scene_context": built.payload,
                        "action_schema": candidate_action_schema(),
                    }
                    session.pending_context_json = json.dumps(
                        pending,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    session.pending_data_preview = built.preview_text
                    session.planning_message = "等待你确认本轮发送数据"
                    _AI_REVIEW_SNAPSHOT = snapshot
                    settings.result_text = "等待确认是否调用 AI"
                    settings.result_detail = "此时尚未联网，也没有修改场景"
                    settings.result_json = ""
                    settings.last_assistant_message = (
                        "本地解析器无法可靠理解这条指令。"
                        "请检查下方数据预览，再决定是否调用 AI。"
                    )
                    _transition(settings, AssistantEvent.AI_REVIEW_READY)
                    return {"FINISHED"}
            settings.result_text, settings.result_detail = _friendly_error(error.code)
            if error.code == ErrorCode.OBJECT_NOT_FOUND and error.details.get("name"):
                settings.result_detail = (
                    f"场景中没有名为 {error.details['name']} 的对象"
                )
            settings.result_json = ""
            settings.last_assistant_message = (
                f"{settings.result_text}。{settings.result_detail}"
            )
            _transition(settings, AssistantEvent.FAILED)
            self.report({"ERROR"}, settings.result_text)
            return {"CANCELLED"}


class BSA_OT_preview_plan(bpy.types.Operator):
    """Create a visible plan without changing the scene."""

    bl_idname = "bsa.preview_plan"
    bl_label = "生成预览"
    bl_description = "只生成确定性计划，不修改任何物体"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_settings
        source = settings.source_object
        target = settings.target_object
        if source is None or target is None:
            settings.last_assistant_message = "请先选择要摆放的物体和目标表面。"
            _transition(settings, AssistantEvent.FAILED)
            self.report({"ERROR"}, "请选择要摆放的物体和目标表面")
            return {"CANCELLED"}
        if source == target:
            settings.last_assistant_message = "两个选项不能是同一物体。"
            _transition(settings, AssistantEvent.FAILED)
            self.report({"ERROR"}, "要摆放的物体不能与目标表面相同")
            return {"CANCELLED"}

        settings.last_user_message = (
            f"精确摆放：{source.name} → {target.name}（{settings.region}）"
        )

        ensure_stable_ids(context.scene.objects)
        source_id = stable_id(source)
        target_id = stable_id(target)
        region_label = {
            "center": "中央",
            "left": "左侧",
            "right": "右侧",
            "front": "前侧",
            "back": "后侧",
        }[settings.region]
        actions = [
            PlaceOnAction(
                action_id="place-1",
                object_id=source_id,
                target_id=target_id,
                region=settings.region,
                clearance=settings.clearance,
            )
        ]
        if settings.lock_target:
            actions.append(LockAction(action_id="lock-1", object_id=target_id))
        plan = ActionPlan(
            schema_version="0.1",
            plan_id=str(uuid4()),
            source="ui",
            scene_fingerprint="",
            requires_confirmation=True,
            actions=tuple(actions),
            constraints=(
                PreserveTransformConstraint(constraint_id="preserve-1", object_id=target_id),
            ),
            user_summary=(
                f"将 {source.name} 放到 {target.name} 的{region_label}"
                + (f"，完成后锁定 {target.name}" if settings.lock_target else "")
            ),
        )
        snapshot = BlenderScenePort(context.scene).read_snapshot()
        plan = replace(
            plan,
            scene_fingerprint=fingerprint_snapshot(snapshot, relevant_object_ids(plan)),
        )
        _store_preview(settings, plan, snapshot)
        return {"FINISHED"}


class BSA_OT_confirm_plan(bpy.types.Operator):
    """Execute the last preview through the transaction service."""

    bl_idname = "bsa.confirm_plan"
    bl_label = "确认并执行"
    bl_description = "重新校验预览后执行；失败时自动回滚"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_settings
        if not settings.plan_json:
            settings.last_assistant_message = "请先让我生成一个可检查的计划。"
            _transition(settings, AssistantEvent.FAILED)
            self.report({"ERROR"}, "请先生成预览")
            return {"CANCELLED"}
        _transition(settings, AssistantEvent.EXECUTION_STARTED)
        try:
            plan = ActionPlan.from_dict(json.loads(settings.plan_json))
            result = SceneEditingService(BlenderScenePort(context.scene)).execute_plan(
                plan, confirmed=True
            )
        except (json.JSONDecodeError, DomainError) as error:
            code = (
                error.code
                if isinstance(error, DomainError)
                else ErrorCode.PLAN_SCHEMA_INVALID
            )
            settings.result_text, settings.result_detail = _friendly_error(code)
            settings.plan_json = ""
            settings.last_assistant_message = (
                f"{settings.result_text}。{settings.result_detail}"
            )
            _transition(settings, AssistantEvent.FAILED)
            self.report({"ERROR"}, settings.result_text)
            return {"CANCELLED"}
        settings.result_json = json.dumps(result.to_dict(), ensure_ascii=False)
        if result.status != "COMMITTED":
            code = result.errors[0].code if result.errors else ErrorCode.INTERNAL_ERROR
            settings.result_text, settings.result_detail = _friendly_error(code)
            settings.plan_json = ""
            settings.last_assistant_message = (
                f"{settings.result_text}。{settings.result_detail}"
            )
            _transition(settings, AssistantEvent.FAILED)
            self.report({"ERROR"}, settings.result_text)
            return {"CANCELLED"}
        checks = result.verification.checks if result.verification else ()
        passed_count = sum(check.passed for check in checks)
        settings.result_text = "成功：修改已提交并通过验证"
        settings.result_detail = f"{passed_count}/{len(checks)} 项检查通过，未授权修改 0"
        settings.plan_json = ""
        settings.preview_text = "上次计划已执行；可输入下一条指令"
        settings.last_assistant_message = (
            f"{settings.result_text}。{settings.result_detail}"
        )
        _transition(settings, AssistantEvent.EXECUTION_SUCCEEDED)
        self.report({"INFO"}, settings.result_text)
        return {"FINISHED"}


class BSA_OT_clear(bpy.types.Operator):
    """Clear the current preview and result without changing objects."""

    bl_idname = "bsa.clear"
    bl_label = "清空"

    def execute(self, context: object) -> set[str]:
        global _AI_REVIEW_SNAPSHOT
        settings = context.scene.bsa_settings
        _clear_pending_ai(context.window_manager.bsa_provider_session)
        _AI_REVIEW_SNAPSHOT = None
        settings.plan_json = ""
        settings.preview_text = "尚未生成计划"
        settings.camera_plan_json = ""
        settings.camera_preview_text = "尚未生成取景计划"
        settings.result_text = "尚未执行操作"
        settings.result_detail = ""
        settings.result_json = ""
        settings.last_user_message = ""
        settings.last_assistant_message = (
            "我已准备好。请告诉我你想怎样调整场景。"
        )
        _transition(settings, AssistantEvent.CLEARED)
        return {"FINISHED"}
