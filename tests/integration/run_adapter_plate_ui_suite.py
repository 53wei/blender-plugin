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


def needs_input_payload():
    return {
        "schema_version": "0.1",
        "status": "needs_input",
        "part_family": "adapter_plate",
        "missing_measurements": [
            {
                "measurement_id": "plate_width",
                "measurement_type": "outer_width",
                "target_id": "adapter_plate",
                "label": "可用板宽",
                "reason": "确定板件外形和孔到边缘距离",
                "unit": "mm",
            }
        ],
        "assumptions": [],
        "user_summary": "请补充可用板宽",
    }


def design_payload():
    return {
        "schema_version": "0.1",
        "status": "design_candidate",
        "part_family": "adapter_plate",
        "design": {
            "plate_id": "adapter-ai-001",
            "width_mm": 80.0,
            "depth_mm": 40.0,
            "thickness_mm": 3.0,
            "corner_radius_mm": 2.0,
            "mounting_patterns": [
                {
                    "pattern_id": "device",
                    "origin_x_mm": 20.0,
                    "origin_y_mm": 20.0,
                    "holes": [
                        {
                            "hole_id": "device-left",
                            "offset_x_mm": -10.0,
                            "offset_y_mm": 0.0,
                            "diameter_mm": 3.2,
                        },
                        {
                            "hole_id": "device-right",
                            "offset_x_mm": 10.0,
                            "offset_y_mm": 0.0,
                            "diameter_mm": 3.2,
                        },
                    ],
                },
                {
                    "pattern_id": "support",
                    "origin_x_mm": 40.0,
                    "origin_y_mm": 20.0,
                    "holes": [
                        {
                            "hole_id": "support-front",
                            "offset_x_mm": 0.0,
                            "offset_y_mm": -10.0,
                            "diameter_mm": 4.2,
                        },
                        {
                            "hole_id": "support-back",
                            "offset_x_mm": 0.0,
                            "offset_y_mm": 10.0,
                            "diameter_mm": 4.2,
                        },
                    ],
                },
            ],
        },
        "assumptions": ["尺寸由用户确认"],
        "user_summary": "生成四孔矩形转接板候选",
    }


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
        adapter_operators = importlib.import_module(package + ".ui.adapter_plate_operators")
        WorkerOutcome = importlib.import_module(
            package + ".infra.provider_process"
        ).WorkerOutcome

        settings = bpy.context.scene.bsa_adapter_plate_settings
        session = bpy.context.window_manager.bsa_provider_session
        if settings.stage != "START" or settings.show_hole_settings:
            raise AssertionError("转接板面板没有以需求入口启动")

        initial = draw(BSA_PT_print_part_assistant, bpy.context)
        if "ai_instruction" not in initial.properties:
            raise AssertionError("首屏没有自然语言需求输入")
        if sum(name == "bsa.prepare_print_intent" for name, _ in initial.buttons) != 1:
            raise AssertionError("首屏主要动作不唯一")

        object_count = len(bpy.context.scene.objects)
        settings.ai_instruction = "做一个连接设备和支架的转接板"
        if bpy.ops.bsa.prepare_print_intent() != {"FINISHED"}:
            raise AssertionError("AI 发送数据准备失败")
        if settings.stage != "AI_REVIEW" or not settings.ai_pending_json:
            raise AssertionError("没有进入发送前确认阶段")
        if len(bpy.context.scene.objects) != object_count:
            raise AssertionError("发送数据确认提前修改了场景")
        review_send = draw(BSA_PT_print_part_assistant, bpy.context)
        if not any(name == "bsa.start_print_intent" for name, _ in review_send.buttons):
            raise AssertionError("发送前确认阶段没有明确同意按钮")

        adapter_operators._apply_print_ai_outcome(
            settings,
            session,
            WorkerOutcome(
                True,
                result={
                    "plan_payload": needs_input_payload(),
                    "usage": {"provider": "fixture", "model": "fixture", "latency_ms": 1},
                    "request_count": 1,
                    "repair_count": 0,
                },
            ),
        )
        if settings.stage != "AI_NEEDS_INPUT" or "可用板宽" not in settings.ai_questions_text:
            raise AssertionError("AI 缺失测量没有成为可回答问题")
        settings.ai_answers = "可用板宽是 80 mm，其余尺寸如下"
        if bpy.ops.bsa.prepare_print_intent() != {"FINISHED"}:
            raise AssertionError("补充测量后无法再次确认发送")
        adapter_operators._apply_print_ai_outcome(
            settings,
            session,
            WorkerOutcome(
                True,
                result={
                    "plan_payload": design_payload(),
                    "usage": {
                        "provider": "fixture",
                        "model": "fixture",
                        "input_tokens": 10,
                        "output_tokens": 20,
                        "latency_ms": 2,
                    },
                    "request_count": 1,
                    "repair_count": 0,
                },
            ),
        )
        if settings.stage != "REVIEW" or not settings.review_fingerprint:
            raise AssertionError("AI 候选没有进入本地确认阶段")
        if settings.review_source != "ai" or settings.width_mm != 80.0:
            raise AssertionError("AI 候选没有转换为可编辑毫米参数")
        if len(bpy.context.scene.objects) != object_count:
            raise AssertionError("AI 候选提前修改了场景")
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
            "natural_language_entry": True,
            "ai_data_review_was_read_only": True,
            "missing_measurement_loop": True,
            "ai_candidate_became_editable_parameters": True,
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

