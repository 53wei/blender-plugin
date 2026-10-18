"""在 Blender 4.5 后台验证转接板正式面板、确认边界与真实创建结果。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy

ROOT = Path(__file__).resolve().parents[2]
INSTALLED = "--installed" in sys.argv


def load_extension():
    module_name = "blender_scene_assistant_adapter_plate_ui"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载扩展包")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class LayoutRecorder:
    def __init__(self) -> None:
        self.labels: list[str] = []
        self.buttons: list[tuple[str, str]] = []
        self.properties: list[str] = []

    def row(self, **_kwargs):
        return self

    column = row
    box = row

    def label(self, *, text="", **_kwargs):
        self.labels.append(text)

    def prop(self, _owner, name, **_kwargs):
        self.properties.append(name)

    def operator(self, name, **kwargs):
        self.buttons.append((name, kwargs.get("text", "")))
        return SimpleNamespace()

    def separator(self, **_kwargs):
        pass


def draw(panel, context):
    recorder = LayoutRecorder()
    panel.draw(SimpleNamespace(layout=recorder), context)
    return recorder


def main() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    extension = None
    registered = False
    try:
        if INSTALLED:
            import addon_utils

            addon_utils.enable(
                "bl_ext.user_default.blender_scene_assistant",
                default_set=False,
                persistent=False,
            )
            package = "bl_ext.user_default.blender_scene_assistant.bsa"
        else:
            extension = load_extension()
            extension.register()
            registered = True
            package = "blender_scene_assistant_adapter_plate_ui.bsa"
        if not hasattr(bpy.types.Scene, "bsa_adapter_plate_settings"):
            raise AssertionError("转接板界面状态没有注册")

        import importlib

        BlenderAdapterPlatePort = importlib.import_module(
            package + ".blender_adapter.adapter_plate_port"
        ).BlenderAdapterPlatePort
        BSA_PT_print_part_assistant = importlib.import_module(
            package + ".ui.adapter_plate_panel"
        ).BSA_PT_print_part_assistant

        settings = bpy.context.scene.bsa_adapter_plate_settings
        if settings.stage != "INPUT" or settings.show_hole_settings:
            raise AssertionError("转接板面板没有以精简输入阶段启动")

        initial = draw(BSA_PT_print_part_assistant, bpy.context)
        if "width_mm" not in initial.properties:
            raise AssertionError("首屏没有板件尺寸")
        if "device_spacing_mm" in initial.properties:
            raise AssertionError("高级孔位参数没有默认折叠")
        if sum(name == "bsa.review_adapter_plate" for name, _ in initial.buttons) != 1:
            raise AssertionError("首屏主要动作不唯一")

        object_count = len(bpy.context.scene.objects)
        if bpy.ops.bsa.review_adapter_plate() != {"FINISHED"}:
            raise AssertionError("参数检查失败")
        if settings.stage != "REVIEW" or not settings.review_fingerprint:
            raise AssertionError("参数检查没有进入确认阶段")
        if len(bpy.context.scene.objects) != object_count:
            raise AssertionError("参数检查提前修改了场景")
        reviewed = draw(BSA_PT_print_part_assistant, bpy.context)
        if not any(name == "bsa.confirm_adapter_plate" for name, _ in reviewed.buttons):
            raise AssertionError("确认阶段没有创建按钮")
        if any(name == "bsa.review_adapter_plate" for name, _ in reviewed.buttons):
            raise AssertionError("确认阶段仍显示输入阶段主要动作")

        settings.width_mm = 81.0
        if settings.stage != "INPUT" or settings.review_fingerprint:
            raise AssertionError("输入变化没有废弃旧检查摘要")
        settings.width_mm = 80.0
        if bpy.ops.bsa.review_adapter_plate() != {"FINISHED"}:
            raise AssertionError("修改后无法重新检查")
        if bpy.ops.bsa.confirm_adapter_plate() != {"FINISHED"}:
            raise AssertionError(settings.result_detail)
        if settings.stage != "SUCCESS":
            raise AssertionError("创建后没有显示成功阶段")

        states = BlenderAdapterPlatePort(bpy.context.scene).read_created_plates(
            settings.last_plan_id
        )
        if len(states) != 1:
            raise AssertionError("没有创建唯一板件")
        state = states[0]
        if not state.is_manifold or state.connected_components != 1:
            raise AssertionError("创建网格不是单一封闭流形")
        if state.through_hole_count != 4:
            raise AssertionError("创建网格没有四个真实贯穿孔")
        completed = draw(BSA_PT_print_part_assistant, bpy.context)
        if not any(name == "bsa.new_adapter_plate" for name, _ in completed.buttons):
            raise AssertionError("成功阶段没有继续入口")
        if "实物打印" not in "".join(completed.labels):
            raise AssertionError("成功阶段缺少实物验证边界")

        report = {
            "blender_version": bpy.app.version_string,
            "installed_package": INSTALLED,
            "input_is_progressive": True,
            "review_was_read_only": True,
            "stale_review_invalidated": True,
            "execution_status": "COMMITTED",
            "verification_passed": True,
            "through_hole_count": state.through_hole_count,
            "is_manifold": state.is_manifold,
            "connected_components": state.connected_components,
        }
        print("BSA_ADAPTER_PLATE_UI_RESULT=" + json.dumps(report, ensure_ascii=True))

        if extension is not None:
            extension.unregister()
            registered = False
            if hasattr(bpy.types.Scene, "bsa_adapter_plate_settings"):
                raise AssertionError("注销后仍残留转接板界面状态")
    finally:
        if registered:
            extension.unregister()


if __name__ == "__main__":
    main()

