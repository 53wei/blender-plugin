"""为带界面的 0.5.0 人工验收准备只读计划，不自动操作窗口。"""

from __future__ import annotations

import bpy


def prepare() -> None:
    """生成可检查的计划，让测试者从真实助手入口继续操作。"""

    if not hasattr(bpy.types.Scene, "bsa_settings"):
        raise AssertionError("已安装扩展未启用")
    settings = bpy.context.scene.bsa_settings
    lamp = bpy.data.objects["Lamp"]
    lamp_before = tuple(lamp.matrix_world.translation)
    settings.instruction = "把 Lamp 放到 Desk 右侧，并锁定 Desk"
    if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
        raise AssertionError("生成验收预览失败")
    if tuple(lamp.matrix_world.translation) != lamp_before:
        raise AssertionError("预览阶段意外移动了物体")
    print("BSA_INTERACTIVE_UI_READY=PLAN_READY")


prepare()
