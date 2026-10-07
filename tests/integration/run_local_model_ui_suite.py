"""真实本地模型的界面闭环验收；只操作脚本创建的一次性夹具。"""

from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import bpy

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmarks.evaluation import load_suite
from tests.integration.run_planning_benchmark import blender_fixture, clean_fixture
from tests.integration.run_provider_ui_suite import load_extension


def main() -> int:
    """验证审查、异步规划、只读预览、确认执行及独立最终位置。"""
    if "--factory-startup" not in sys.argv or bpy.data.filepath or not bpy.app.online_access:
        raise RuntimeError("必须出厂启动、允许联网且不能加载用户文件")
    if "--installed" in sys.argv:
        import addon_utils
        addon_utils.enable("bl_ext.user_default.blender_scene_assistant", default_set=False)
        package = "bl_ext.user_default.blender_scene_assistant.bsa"
        extension = None
    else:
        extension = load_extension()
        extension.register()
        package = "blender_scene_assistant_provider_integration.bsa"
    operators = importlib.import_module(package + ".ui.operators")
    case = next(item for item in load_suite()["cases"] if item["case_id"] == "ai_01")
    started = time.perf_counter()
    try:
        scene = blender_fixture(case)
        before = scene.read_snapshot()
        settings = bpy.context.scene.bsa_settings
        session = bpy.context.window_manager.bsa_provider_session
        session.api_base = "http://127.0.0.1:1234/v1"
        session.model = "qwen/qwen3-4b-2507"
        session.output_format = "json_schema"
        session.api_key = ""
        session.timeout_seconds = 60
        settings.instruction = case["instruction"]
        assert bpy.ops.bsa.preview_instruction() == {"FINISHED"}
        assert settings.assistant_status == "AI_REVIEW"
        assert scene.read_snapshot().objects == before.objects
        assert bpy.ops.bsa.start_ai_planning() == {"FINISHED"}
        deadline = time.monotonic() + 125
        while settings.assistant_status == "PLANNING" and time.monotonic() < deadline:
            operators._poll_ai_task()
            time.sleep(0.05)
        assert settings.assistant_status == "PLAN_READY", settings.last_assistant_message
        assert scene.read_snapshot().objects == before.objects, "确认前场景发生修改"
        assert "实际执行动作" in settings.preview_text
        assert session.last_request_count <= 2
        assert bpy.ops.bsa.confirm_plan() == {"FINISHED"}
        result = json.loads(settings.result_json)
        assert result["status"] == "COMMITTED" and result["verification"]["passed"]
        after = scene.read_snapshot().object_map()
        expected = (1.78, 0.0, 1.5)
        assert max(abs(a - b) for a, b in zip(after["lamp-id"].location_world, expected)) <= 1e-4
        assert after["desk-id"] == before.object_map()["desk-id"]
        assert after["chair-id"] == before.object_map()["chair-id"]
        report = {
            "extension_version": importlib.import_module(package).__version__,
            "blender_version": bpy.app.version_string, "mode": "live_local_ui",
            "model": session.model, "output_format": session.output_format,
            "installed_package": "--installed" in sys.argv,
            "ai_data_review_required": True, "preview_was_read_only": True,
            "confirmed_execution_verified": True, "independent_task_goal_passed": True,
            "task_unauthorized_changes": [], "network_requests": session.last_request_count,
            "repair_count": session.last_repair_count,
            "input_tokens": session.last_input_tokens if session.last_usage_available else None,
            "output_tokens": session.last_output_tokens if session.last_usage_available else None,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        name = "qwen_local_installed_ui_2026_10_07.json" if "--installed" in sys.argv else "qwen_local_source_ui_2026_10_07.json"
        output = REPOSITORY_ROOT / "benchmarks" / "results" / name
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("BSA_LOCAL_MODEL_UI_RESULT=" + json.dumps(report, ensure_ascii=True))
        return 0
    finally:
        if operators._AI_TASK is not None:
            bpy.ops.bsa.cancel_ai_planning()
        clean_fixture()
        if extension is not None:
            extension.unregister()


if __name__ == "__main__":
    raise SystemExit(main())
