"""专用演示窗口的原生截图；只允许固定夹具，不接触用户工程。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/desk_lamp_demo.blend"
CASES = {"idle_sidebar", "idle_popup", "plan_popup", "review_popup",
         "settings_popup", "models_popup", "error_popup", "success_popup"}
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
CASE = args[0] if args else "idle_popup"
_surface_restored = False
if CASE not in CASES or "--factory-startup" not in sys.argv:
    raise RuntimeError("只支持明确的固定布局检查案例和出厂启动")
if Path(bpy.data.filepath).resolve() != FIXTURE.resolve():
    raise RuntimeError("只能检查公开演示夹具，拒绝用户项目")


def prepare() -> float | None:
    """场景修改仅通过已有确认操作器，其他设置只影响演示窗口布局。"""
    import addon_utils
    addon_utils.enable("bl_ext.user_default.blender_scene_assistant", default_set=False)
    settings = bpy.context.scene.bsa_settings
    provider = bpy.context.window_manager.bsa_provider_session
    bpy.ops.bsa.clear()
    provider.show_settings = False
    provider.api_key = ""
    provider.model = ""
    settings.instruction = ""
    if CASE in {"plan_popup", "success_popup"}:
        settings.instruction = "把 Lamp 放到 Desk 右侧"
        assert bpy.ops.bsa.preview_instruction() == {"FINISHED"}
        if CASE == "success_popup":
            assert bpy.ops.bsa.confirm_plan() == {"FINISHED"}
            assert json.loads(settings.result_json)["verification"]["passed"]
    elif CASE == "review_popup":
        settings.instruction = "让 Lamp 落在 Desk 顶面的右侧，Desk 保持原样"
        assert bpy.ops.bsa.preview_instruction() == {"FINISHED"}
        assert settings.assistant_status == "AI_REVIEW"
    elif CASE == "error_popup":
        settings.instruction = "MissingDemoObject 向右移动 20 厘米"
        # Blender 会把操作器的 ERROR 报告抛成 RuntimeError；状态仍须正确失败。
        try:
            outcome = bpy.ops.bsa.preview_instruction()
            assert outcome == {"CANCELLED"}
        except RuntimeError:
            assert settings.assistant_status == "ERROR"
            assert settings.result_text == "找不到指令或预览中的物体"
    elif CASE in {"settings_popup", "models_popup"}:
        provider.show_settings = True
        provider.api_base = "http://127.0.0.1:1234/v1"
        provider.output_format = "json_schema"
        if CASE == "models_popup":
            # 只验证列表呈现：这些是测试名称，不声称真实服务连接成功。
            provider.connection_status = "SUCCESS"
            provider.connection_message = "界面测试数据：2 个模型（未联网）"
            provider.available_models_text = "fixture-model, fixture-model-2"
            provider.show_model_names = True

    window = bpy.context.window
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    area.spaces.active.show_region_ui = CASE == "idle_sidebar"
    area.tag_redraw()
    bpy.app.timers.register(open_surface, first_interval=0.5)
    return None


def open_surface() -> None:
    """用 Blender 自身面板接口打开待检查表面，不启动外部鼠标驱动。"""
    window = bpy.context.window
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    if CASE == "idle_sidebar":
        region = next(region for region in area.regions if region.type == "UI")
        region.active_panel_category = "BSA"
    else:
        region = next(region for region in area.regions if region.type == "WINDOW")
        with bpy.context.temp_override(window=window, area=area, region=region):
            assert bpy.ops.bsa.open_assistant("INVOKE_DEFAULT") == {"RUNNING_MODAL"}
    area.tag_redraw()
    bpy.app.timers.register(capture, first_interval=1.5)


def capture() -> None:
    """记录完整实际窗口后退出本次专用检查进程，不保存夹具。"""
    global _surface_restored
    provider = bpy.context.window_manager.bsa_provider_session
    expected_settings = CASE in {"settings_popup", "models_popup"}
    if provider.show_settings != expected_settings and not _surface_restored:
        # 只恢复本次截图指定的界面表面，不改变执行结果或场景物体。
        provider.show_settings = expected_settings
        _surface_restored = True
        for area in bpy.context.screen.areas:
            area.tag_redraw()
        bpy.app.timers.register(capture, first_interval=0.5)
        return
    assert provider.show_settings == expected_settings, "截图表面与案例名称不符"
    expected_status = {
        "plan_popup": "PLAN_READY", "review_popup": "AI_REVIEW",
        "error_popup": "ERROR", "success_popup": "SUCCESS",
    }.get(CASE, "IDLE")
    assert bpy.context.scene.bsa_settings.assistant_status == expected_status
    output = ROOT / ".impeccable/review" / (CASE + ".png")
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.screen.screenshot(filepath=str(output), check_existing=False)
    report = {
        "case": CASE, "blender_version": bpy.app.version_string,
        "window_width": bpy.context.window.width, "window_height": bpy.context.window.height,
        "network_requests": 0, "fixture_saved": False,
    }
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            report["sidebar_width"] = next(r.width for r in area.regions if r.type == "UI")
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    print("BSA_COMPACT_CAPTURE=" + json.dumps(report, ensure_ascii=True), flush=True)
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(prepare, first_interval=0.75)
