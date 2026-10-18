"""矩形转接板面板操作器；所有场景写入都委托给创建事务。"""

from __future__ import annotations

from uuid import uuid4

import bpy

from ..application.adapter_plate_service import AdapterPlateCreationService
from ..application.adapter_plate_ui import (
    AdapterPlateForm,
    build_adapter_plate_creation_plan,
    review_adapter_plate_form,
)
from ..application.ui_presentation import POPUP_WIDTH_PX
from ..blender_adapter.adapter_plate_port import BlenderAdapterPlatePort
from ..domain.errors import DomainError, ErrorCode


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
        settings.stage = "INPUT"
        return {"FINISHED"}

