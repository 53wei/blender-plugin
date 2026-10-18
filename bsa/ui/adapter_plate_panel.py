"""渐进呈现的 3D 打印矩形转接板原生侧栏。"""

from __future__ import annotations

import bpy

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


def draw_adapter_plate(owner: object, context: object) -> None:
    layout = owner.layout
    layout.use_property_decorate = False
    settings = context.scene.bsa_adapter_plate_settings
    width = _width(owner, context)

    heading = layout.row()
    heading.label(text="矩形转接板 · 本地创建", icon="MESH_CUBE")
    layout.separator()

    if settings.stage == "REVIEW":
        layout.label(text="第 2 步 / 2 · 检查设计", icon="PREVIEW_RANGE")
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

