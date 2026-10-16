"""简洁原生界面记录器验收：只在出厂启动的一次性场景检查。"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.integration.run_provider_ui_suite import load_extension


class LayoutRecorder:
    """记录实际 draw 路径，不伪造操作器、事务或验证结果。"""

    def __init__(self) -> None:
        self.labels = []
        self.buttons = []
        self.properties = []
        self.large_icons = 0

    def row(self, **_kwargs):
        return self

    column = row
    box = row
    split = row

    def label(self, *, text="", **_kwargs):
        self.labels.append(text)

    def prop(self, _owner, name, **_kwargs):
        self.properties.append(name)

    def operator(self, name, **kwargs):
        self.buttons.append((name, kwargs.get("text", "")))
        return SimpleNamespace()

    def separator(self, **_kwargs):
        pass

    def template_icon(self, **_kwargs):
        self.large_icons += 1


def main() -> int:
    if "--factory-startup" not in sys.argv or bpy.data.filepath:
        raise RuntimeError("必须出厂启动，不加载用户项目")
    if "--installed" in sys.argv:
        import addon_utils
        addon_utils.enable("bl_ext.user_default.blender_scene_assistant", default_set=False)
        package = "bl_ext.user_default.blender_scene_assistant.bsa"
        extension = None
    else:
        extension = load_extension()
        extension.register()
        package = "blender_scene_assistant_provider_integration.bsa"
    panel = importlib.import_module(package + ".ui.panel").BSA_PT_scene_assistant
    operators = importlib.import_module(package + ".ui.operators")
    worker_outcome = importlib.import_module(package + ".infra.provider_process").WorkerOutcome
    settings = bpy.context.scene.bsa_settings
    session = bpy.context.window_manager.bsa_provider_session
    matrices = {obj.name: tuple(v for row in obj.matrix_world for v in row)
                for obj in bpy.context.scene.objects}
    try:
        assert session.show_settings is False
        def draw():
            recorder = LayoutRecorder()
            panel.draw(SimpleNamespace(layout=recorder, bl_idname=panel.bl_idname), bpy.context)
            assert recorder.large_icons == 0, "面板仍显示大头像"
            return recorder

        # 旧 .blend 可能保存了手动表单展开状态，也不能挤占新主屏。
        settings.show_manual_controls = True
        idle = draw()
        assert "instruction" in idle.properties
        assert "api_base" not in idle.properties and "source_object" not in idle.properties
        assert "show_avatar" not in idle.properties
        assert not any(text in {"对话", "你", "场景领航员"} for text in idle.labels)
        assert sum(name == "bsa.preview_instruction" for name, _text in idle.buttons) == 1

        settings.assistant_status = "ERROR"
        settings.result_text = "示例失败"
        settings.result_detail = "输入保留，场景未变"
        error = draw()
        assert error.labels.count("示例失败") == 1
        assert "instruction" in error.properties

        settings.plan_json = "{}"
        settings.preview_text = "实际执行动作：\n1. 移动 Cube\n保护约束：\n保持 Desk 不动"
        settings.assistant_status = "PLAN_READY"
        ready = draw()
        assert any(name == "bsa.confirm_plan" for name, _text in ready.buttons)
        assert not any(name == "bsa.preview_instruction" for name, _text in ready.buttons)
        assert "保持 Desk 不动" in ready.labels
        before_plan = settings.plan_json
        assert bpy.ops.bsa.toggle_settings() == {"FINISHED"}
        config = draw()
        assert "api_base" in config.properties and "model" in config.properties
        assert "show_avatar" in config.properties
        assert settings.plan_json == before_plan
        session.connection_status = "SUCCESS"
        session.connection_message = "连接成功，共发现 2 个模型"
        session.available_models_text = "fixture-model, fixture-model-2"
        models_closed = draw()
        assert "show_model_names" in models_closed.properties
        assert "fixture-model, fixture-model-2" not in models_closed.labels
        session.show_model_names = True
        assert "fixture-model, fixture-model-2" in draw().labels
        assert bpy.ops.bsa.toggle_settings() == {"FINISHED"}
        assert "fixture-model, fixture-model-2" not in draw().labels
        assert settings.plan_json == before_plan

        settings.plan_json = ""
        settings.assistant_status = "AI_REVIEW"
        session.pending_context_json = json.dumps({
            "instruction": "安排 Cube", "scene_context": {
                "unit_scale": 1.0, "objects": [{"name": "Cube", "object_id": "cube-id"}]
            }
        })
        session.pending_data_preview = "Cube 的完整发送数据"
        session.model = ""
        unconfigured = draw()
        assert not any(name == "bsa.start_ai_planning" for name, _text in unconfigured.buttons)
        session.model = "fixture-model"
        configured = draw()
        assert any(name == "bsa.start_ai_planning" for name, _text in configured.buttons)
        session.show_data_details = True
        assert "Cube 的完整发送数据" in draw().labels

        settings.assistant_status = "PLANNING"
        planning = draw()
        assert any(name == "bsa.cancel_ai_planning" for name, _text in planning.buttons)
        assert not any(name == "bsa.preview_instruction" for name, _text in planning.buttons)
        for status in ("SUCCESS", "WORKING"):
            settings.assistant_status = status
            draw()

        settings.assistant_status = "PLANNING"
        operators._apply_ai_outcome(
            settings,
            session,
            worker_outcome(
                False,
                error={
                    "code": "INVALID_RESPONSE",
                    "message": "模型响应缺少 choices",
                },
            ),
        )
        assert settings.assistant_status == "ERROR"
        assert settings.result_text == "模型响应缺少 choices"

        assert matrices == {obj.name: tuple(v for row in obj.matrix_world for v in row)
                            for obj in bpy.context.scene.objects}
        report = {
            "extension_version": importlib.import_module(package).__version__,
            "installed_package": "--installed" in sys.argv,
            "blender_version": bpy.app.version_string,
            "idle_is_compact": True, "error_shown_once": True,
            "trusted_plan_visible": True, "settings_preserve_plan": True,
            "unconfigured_ai_has_recovery": True, "complete_data_details_accessible": True,
            "cancel_visible": True, "large_panel_portrait_removed": True,
            "scene_transforms_unchanged": True,
            "available_model_names_accessible_in_settings": True,
            "provider_response_error_is_specific": True,
        }
        output = ROOT / "benchmarks/results/compact_ui_0_6_3.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("BSA_COMPACT_UI_RESULT=" + json.dumps(report, ensure_ascii=True))
        return 0
    finally:
        if extension is not None:
            extension.unregister()


if __name__ == "__main__":
    raise SystemExit(main())
