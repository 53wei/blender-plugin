"""矩形转接板面板操作器；所有场景写入都委托给创建事务。"""

from __future__ import annotations

import json
from urllib.parse import urlsplit
from uuid import uuid4

import bpy

from ..application.adapter_plate_service import AdapterPlateCreationService
from ..application.adapter_plate_ui import (
    AdapterPlateForm,
    build_adapter_plate_creation_plan,
    review_adapter_plate_form,
)
from ..application.print_design_assistant import (
    build_print_intent_request,
    describe_missing_measurements,
    form_from_design_candidate,
    print_request_preview,
)
from ..application.ui_presentation import POPUP_WIDTH_PX, provider_error_message
from ..blender_adapter.adapter_plate_port import BlenderAdapterPlatePort
from ..domain.errors import DomainError, ErrorCode
from ..infra.credentials import CredentialSource, resolve_api_key
from ..infra.provider_process import ProviderWorkerTask, WorkerOutcome
from ..planner.openai_compatible import (
    ProviderConnectionConfig,
    ProviderError,
    ProviderErrorCode,
)
from ..planner.print_intent_candidate import PrintIntentCandidate
from ..planner.print_intent_provider import PrintIntentRequest


_PRINT_AI_TASK: ProviderWorkerTask | None = None
_PRINT_AI_TIMER_ACTIVE = False

_CREDENTIAL_LABELS = {
    CredentialSource.SESSION: "本次会话输入",
    CredentialSource.BSA_ENV: "环境变量 BSA_API_KEY",
    CredentialSource.OPENAI_ENV: "环境变量 OPENAI_API_KEY",
    CredentialSource.NONE: "未提供",
}


def _form(settings: object) -> AdapterPlateForm:
    return AdapterPlateForm(
        plate_id=settings.plate_id,
        width_mm=settings.width_mm,
        depth_mm=settings.depth_mm,
        thickness_mm=settings.thickness_mm,
        corner_radius_mm=settings.corner_radius_mm,
        device_center_x_mm=settings.device_center_x_mm,
        device_center_y_mm=settings.device_center_y_mm,
        device_spacing_mm=settings.device_spacing_mm,
        device_hole_diameter_mm=settings.device_hole_diameter_mm,
        support_center_x_mm=settings.support_center_x_mm,
        support_center_y_mm=settings.support_center_y_mm,
        support_spacing_mm=settings.support_spacing_mm,
        support_hole_diameter_mm=settings.support_hole_diameter_mm,
    )


def _clear_transient(settings: object) -> None:
    settings.review_fingerprint = ""
    settings.review_summary = ""
    settings.review_details = ""
    settings.review_notice = ""
    settings.error_message = ""
    settings.result_summary = ""
    settings.result_detail = ""
    settings.last_plan_id = ""


def _show_error(settings: object, message: str, *, expand_holes: bool = False) -> None:
    settings.stage = "ERROR"
    settings.error_message = message
    settings.result_summary = ""
    settings.result_detail = ""
    settings.last_plan_id = ""
    if expand_holes:
        settings.show_hole_settings = True


def _show_ai_error(settings: object, message: str) -> None:
    settings.stage = "AI_ERROR"
    settings.ai_message = message
    settings.ai_pending_json = ""
    settings.ai_data_preview = ""


def _set_form(settings: object, form: AdapterPlateForm) -> None:
    """只更新参数状态；不会创建或修改 Blender 对象。"""

    for field in (
        "plate_id",
        "width_mm",
        "depth_mm",
        "thickness_mm",
        "corner_radius_mm",
        "device_center_x_mm",
        "device_center_y_mm",
        "device_spacing_mm",
        "device_hole_diameter_mm",
        "support_center_x_mm",
        "support_center_y_mm",
        "support_spacing_mm",
        "support_hole_diameter_mm",
    ):
        setattr(settings, field, getattr(form, field))


def _store_usage(session: object, outcome: WorkerOutcome) -> None:
    usage = outcome.result.get("usage", {})
    if not isinstance(usage, dict):
        return
    session.last_plan_source = "llm_print_intent"
    session.last_provider = str(usage.get("provider", ""))
    session.last_model = str(usage.get("model", ""))
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    session.last_usage_available = isinstance(input_tokens, int) and isinstance(
        output_tokens, int
    )
    session.last_input_tokens = input_tokens if isinstance(input_tokens, int) else 0
    session.last_output_tokens = output_tokens if isinstance(output_tokens, int) else 0
    session.last_planning_latency_ms = max(0, int(usage.get("latency_ms", 0)))
    session.last_request_count = max(0, int(outcome.result.get("request_count", 0)))
    session.last_repair_count = max(0, int(outcome.result.get("repair_count", 0)))


def _apply_print_ai_outcome(
    settings: object,
    session: object,
    outcome: WorkerOutcome,
) -> None:
    """在 Blender 主线程接收不可信候选，并仅写入界面参数。"""

    settings.ai_pending_json = ""
    settings.ai_data_preview = ""
    if not outcome.ok:
        code = str(outcome.error.get("code", ProviderErrorCode.WORKER_FAILED.value))
        detail = str(outcome.error.get("message", ""))
        _show_ai_error(settings, provider_error_message(code, detail))
        return
    try:
        payload = outcome.result.get("plan_payload")
        if not isinstance(payload, dict):
            raise ValueError("missing candidate")
        candidate = PrintIntentCandidate.from_dict(payload)
        _store_usage(session, outcome)
        if candidate.status == "needs_input":
            settings.ai_previous_candidate_json = json.dumps(
                candidate.to_dict(), ensure_ascii=False, separators=(",", ":")
            )
            settings.ai_questions_text = describe_missing_measurements(candidate)
            settings.ai_answers = ""
            settings.ai_message = candidate.user_summary
            settings.stage = "AI_NEEDS_INPUT"
            return
        if candidate.status == "parameter_patch":
            raise DomainError(
                ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
                "创建后自然语言修改尚未接入安全网格修改事务",
            )
        form = form_from_design_candidate(candidate)
        _set_form(settings, form)
        # Blender FloatProperty 会量化为自身精度；必须对实际写入后的值生成指纹，
        # 不能用 Provider 返回的 Python float 绕过 stale-review 防护。
        review = review_adapter_plate_form(_form(settings))
        settings.review_fingerprint = review.fingerprint
        settings.review_summary = review.summary
        settings.review_details = review.details
        settings.review_notice = (
            "这是 AI 候选，已通过本地结构与几何检查；"
            "请核对毫米尺寸。确认前场景尚未修改。"
        )
        settings.review_source = "ai"
        settings.ai_message = candidate.user_summary
        settings.ai_previous_candidate_json = ""
        settings.ai_questions_text = ""
        settings.ai_answers = ""
        settings.error_message = ""
        settings.stage = "REVIEW"
    except DomainError as error:
        _show_ai_error(settings, error.message)
    except (TypeError, ValueError, json.JSONDecodeError):
        _show_ai_error(settings, "AI 返回的零件候选无法安全转换，场景没有修改")


def _poll_print_ai_task() -> float | None:
    global _PRINT_AI_TASK, _PRINT_AI_TIMER_ACTIVE
    if not _PRINT_AI_TIMER_ACTIVE or _PRINT_AI_TASK is None:
        _PRINT_AI_TIMER_ACTIVE = False
        return None
    try:
        outcome = _PRINT_AI_TASK.poll()
    except Exception:
        if hasattr(bpy.types.Scene, "bsa_adapter_plate_settings"):
            _show_ai_error(
                bpy.context.scene.bsa_adapter_plate_settings,
                "AI 子进程异常结束，请检查服务设置后重试；场景没有修改",
            )
        try:
            _PRINT_AI_TASK.cancel()
        finally:
            _PRINT_AI_TASK = None
            _PRINT_AI_TIMER_ACTIVE = False
        return None
    if outcome is None:
        return 0.1
    try:
        if hasattr(bpy.types.Scene, "bsa_adapter_plate_settings"):
            _apply_print_ai_outcome(
                bpy.context.scene.bsa_adapter_plate_settings,
                bpy.context.window_manager.bsa_provider_session,
                outcome,
            )
    finally:
        _PRINT_AI_TASK = None
        _PRINT_AI_TIMER_ACTIVE = False
    return None


def cancel_print_provider_task() -> None:
    """注销扩展时终止零件 AI 子进程。"""

    global _PRINT_AI_TASK, _PRINT_AI_TIMER_ACTIVE
    if _PRINT_AI_TASK is not None:
        _PRINT_AI_TASK.cancel()
    _PRINT_AI_TASK = None
    _PRINT_AI_TIMER_ACTIVE = False


class BSA_OT_open_print_part(bpy.types.Operator):
    """从右下角助手打开当前 3D 打印零件流程。"""

    bl_idname = "bsa.open_print_part"
    bl_label = "打开 3D 打印零件"
    bl_description = "打开矩形转接板的参数、检查和创建界面"

    def invoke(self, context: object, _event: object) -> set[str]:
        return context.window_manager.invoke_popup(self, width=POPUP_WIDTH_PX)

    def draw(self, context: object) -> None:
        from .adapter_plate_panel import draw_adapter_plate

        draw_adapter_plate(self, context)

    def execute(self, _context: object) -> set[str]:
        return {"FINISHED"}


class BSA_OT_prepare_print_intent(bpy.types.Operator):
    """本地准备并展示零件 AI 请求；此操作不联网。"""

    bl_idname = "bsa.prepare_print_intent"
    bl_label = "分析需求"
    bl_description = "先展示本轮将发送的数据；不会立即联网或修改场景"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_adapter_plate_settings
        previous = None
        try:
            if settings.ai_previous_candidate_json:
                raw = json.loads(settings.ai_previous_candidate_json)
                if not isinstance(raw, dict):
                    raise ValueError("invalid previous candidate")
                previous = PrintIntentCandidate.from_dict(raw)
            request = build_print_intent_request(
                settings.ai_instruction,
                previous_candidate=previous,
                measurement_answers=settings.ai_answers,
            )
        except (DomainError, TypeError, ValueError, json.JSONDecodeError) as error:
            message = error.message if isinstance(error, DomainError) else str(error)
            _show_ai_error(settings, message or "请先填写零件需求")
            self.report({"WARNING"}, settings.ai_message)
            return {"CANCELLED"}
        settings.ai_pending_json = json.dumps(
            request.to_dict(), ensure_ascii=False, separators=(",", ":")
        )
        settings.ai_data_preview = print_request_preview(request)
        settings.ai_message = "请确认下方数据后再调用 AI"
        settings.stage = "AI_REVIEW"
        return {"FINISHED"}


class BSA_OT_start_print_intent(bpy.types.Operator):
    """经用户确认后在隔离子进程中请求严格零件候选。"""

    bl_idname = "bsa.start_print_intent"
    bl_label = "同意并调用 AI"
    bl_description = "发送已展示的数据；AI 只返回候选参数，不直接建模"

    def execute(self, context: object) -> set[str]:
        global _PRINT_AI_TASK, _PRINT_AI_TIMER_ACTIVE
        settings = context.scene.bsa_adapter_plate_settings
        session = context.window_manager.bsa_provider_session
        if settings.stage != "AI_REVIEW" or not settings.ai_pending_json:
            _show_ai_error(settings, "待发送数据已经失效，请重新检查")
            return {"CANCELLED"}
        if _PRINT_AI_TASK is not None:
            self.report({"WARNING"}, "零件 AI 请求正在进行")
            return {"CANCELLED"}
        try:
            pending = json.loads(settings.ai_pending_json)
            if not isinstance(pending, dict):
                raise ValueError("invalid pending request")
            requested = pending.get("requested_measurements", [])
            if not isinstance(requested, list) or not all(
                isinstance(item, dict) for item in requested
            ):
                raise ValueError("invalid requested measurements")
            request = PrintIntentRequest(
                instruction=str(pending.get("instruction", "")),
                requested_measurements=tuple(requested),
                measurement_answers=str(pending.get("measurement_answers", "")),
            )
            config = ProviderConnectionConfig(
                api_base=session.api_base,
                model=session.model,
                timeout_seconds=session.timeout_seconds,
                output_format=session.output_format,
            ).validated_for_planning()
        except (TypeError, ValueError, json.JSONDecodeError):
            _show_ai_error(settings, "待发送数据格式无效，请重新开始")
            return {"CANCELLED"}
        except ProviderError as error:
            _show_ai_error(settings, provider_error_message(error))
            return {"CANCELLED"}
        if not getattr(bpy.app, "online_access", True):
            _show_ai_error(settings, "Blender 当前禁止扩展联网，请在系统设置中允许联网")
            return {"CANCELLED"}
        credential = resolve_api_key(session.api_key)
        host = (urlsplit(config.api_base).hostname or "").lower()
        if not credential.value and host not in {"localhost", "127.0.0.1", "::1"}:
            _show_ai_error(settings, "远程服务需要 API Key；请展开 AI 服务设置")
            return {"CANCELLED"}
        try:
            _PRINT_AI_TASK = ProviderWorkerTask.start_print_intent(
                config,
                credential.value,
                request,
            )
        except ProviderError as error:
            _show_ai_error(settings, provider_error_message(error))
            return {"CANCELLED"}
        session.credential_source = _CREDENTIAL_LABELS[credential.source]
        settings.ai_message = "AI 正在整理需求；场景尚未修改"
        settings.stage = "AI_WORKING"
        _PRINT_AI_TIMER_ACTIVE = True
        bpy.app.timers.register(_poll_print_ai_task, first_interval=0.1)
        return {"FINISHED"}


class BSA_OT_cancel_print_intent(bpy.types.Operator):
    """取消零件 AI 请求，保持场景不变。"""

    bl_idname = "bsa.cancel_print_intent"
    bl_label = "取消分析"

    def execute(self, context: object) -> set[str]:
        global _PRINT_AI_TASK, _PRINT_AI_TIMER_ACTIVE
        if _PRINT_AI_TASK is not None:
            _PRINT_AI_TASK.cancel()
        _PRINT_AI_TASK = None
        _PRINT_AI_TIMER_ACTIVE = False
        settings = context.scene.bsa_adapter_plate_settings
        _show_ai_error(settings, "已取消 AI 分析，场景没有修改")
        return {"FINISHED"}


class BSA_OT_manual_adapter_plate(bpy.types.Operator):
    """跳过 AI，直接使用确定性参数表单。"""

    bl_idname = "bsa.manual_adapter_plate"
    bl_label = "直接填写尺寸"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_adapter_plate_settings
        settings.ai_pending_json = ""
        settings.ai_data_preview = ""
        settings.stage = "INPUT"
        return {"FINISHED"}


class BSA_OT_back_print_start(bpy.types.Operator):
    """放弃当前发送预览，返回需求或补充信息阶段。"""

    bl_idname = "bsa.back_print_start"
    bl_label = "返回修改"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_adapter_plate_settings
        settings.ai_pending_json = ""
        settings.ai_data_preview = ""
        settings.stage = (
            "AI_NEEDS_INPUT" if settings.ai_previous_candidate_json else "START"
        )
        return {"FINISHED"}


class BSA_OT_review_adapter_plate(bpy.types.Operator):
    """本地检查表单并显示确定性设计摘要，不修改场景。"""

    bl_idname = "bsa.review_adapter_plate"
    bl_label = "检查参数"
    bl_description = "在本机检查板件和孔位，并显示确认摘要；不会创建物体"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_adapter_plate_settings
        try:
            review = review_adapter_plate_form(_form(settings))
        except DomainError as error:
            _show_error(settings, error.message, expand_holes=True)
            self.report({"ERROR"}, error.message)
            return {"CANCELLED"}
        except Exception:
            message = "无法检查这些参数，请恢复默认值后重试"
            _show_error(settings, message, expand_holes=True)
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        settings.review_fingerprint = review.fingerprint
        settings.review_summary = review.summary
        settings.review_details = review.details
        settings.review_notice = review.notice
        settings.error_message = ""
        settings.result_summary = ""
        settings.result_detail = ""
        settings.last_plan_id = ""
        settings.stage = "REVIEW"
        return {"FINISHED"}


class BSA_OT_confirm_adapter_plate(bpy.types.Operator):
    """确认当前摘要，并只通过受验证事务创建真实网格。"""

    bl_idname = "bsa.confirm_adapter_plate"
    bl_label = "确认并创建"
    bl_description = "创建一个真实贯穿孔网格；失败会自动恢复创建前场景"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_adapter_plate_settings
        if settings.stage != "REVIEW" or not settings.review_fingerprint:
            message = "检查摘要已经失效，请重新检查参数"
            _show_error(settings, message)
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        try:
            review = review_adapter_plate_form(_form(settings))
            if review.fingerprint != settings.review_fingerprint:
                raise DomainError(
                    ErrorCode.PLAN_SCHEMA_INVALID,
                    "参数已改变，请重新检查后再创建",
                )
            plan = build_adapter_plate_creation_plan(
                review,
                plan_id=f"adapter-ui-{uuid4().hex}",
            )
        except DomainError as error:
            _show_error(settings, error.message, expand_holes=True)
            self.report({"ERROR"}, error.message)
            return {"CANCELLED"}

        settings.stage = "WORKING"
        port = BlenderAdapterPlatePort(context.scene)
        result = AdapterPlateCreationService(port).execute_plan(
            plan,
            confirmed=True,
        )
        if result.status != "COMMITTED":
            error = (
                result.errors[0]
                if result.errors
                else DomainError(ErrorCode.INTERNAL_ERROR, "转接板创建没有完成")
            )
            recovery = (
                "自动恢复验证失败，请立即使用 Blender 撤销并保存备份"
                if result.status == "ROLLBACK_FAILED"
                else (
                    "已自动恢复创建前场景，请修改参数或零件编号后重试"
                    if result.status == "ROLLED_BACK"
                    else "场景没有修改，请修改参数或零件编号后重试"
                )
            )
            _show_error(settings, f"{error.message}。{recovery}")
            self.report({"ERROR"}, error.message)
            return {"CANCELLED"}

        verification = result.verification
        checks = verification.checks if verification else ()
        passed = sum(check.passed for check in checks)
        settings.stage = "SUCCESS"
        settings.last_plan_id = plan.plan_id
        settings.result_summary = "模型已创建，并通过实际网格验证"
        settings.result_detail = (
            f"{passed}/{len(checks)} 项检查通过；单一封闭网格，"
            f"{len(review.design.holes)} 个真实贯穿孔；既有场景未改动。"
        )
        settings.error_message = ""
        settings.review_fingerprint = ""
        self.report({"INFO"}, settings.result_summary)
        return {"FINISHED"}


class BSA_OT_edit_adapter_plate(bpy.types.Operator):
    """保留当前参数并返回输入阶段。"""

    bl_idname = "bsa.edit_adapter_plate"
    bl_label = "返回修改"
    bl_description = "保留当前数值并返回参数编辑"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_adapter_plate_settings
        _clear_transient(settings)
        settings.stage = "INPUT"
        return {"FINISHED"}


class BSA_OT_new_adapter_plate(bpy.types.Operator):
    """保留尺寸并为下一块板选择未占用编号。"""

    bl_idname = "bsa.new_adapter_plate"
    bl_label = "继续创建"
    bl_description = "保留当前尺寸，为下一块板自动使用新的零件编号"

    def execute(self, context: object) -> set[str]:
        settings = context.scene.bsa_adapter_plate_settings
        port = BlenderAdapterPlatePort(context.scene)
        for index in range(1, 10000):
            candidate = f"adapter-{index:03d}"
            if not port.plate_exists(candidate):
                settings.plate_id = candidate
                break
        else:
            message = "无法自动分配新的零件编号，请手动修改"
            _show_error(settings, message)
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        _clear_transient(settings)
        settings.ai_instruction = ""
        settings.ai_answers = ""
        settings.ai_previous_candidate_json = ""
        settings.ai_questions_text = ""
        settings.stage = "START"
        return {"FINISHED"}

