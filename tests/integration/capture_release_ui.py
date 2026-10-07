"""在 Blender 图形窗口中打开 0.5.0 Provider 面板并保存发布验收图。"""

from __future__ import annotations

from pathlib import Path

import bpy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_PATH = REPOSITORY_ROOT / "docs" / "images" / "ui_0_5_0_provider.png"


def prepare() -> None:
    """展开连接设置并从真实 3D 视图上下文打开助手浮层。"""

    if not hasattr(bpy.types.Scene, "bsa_settings"):
        raise AssertionError("已安装扩展未启用")

    settings = bpy.context.scene.bsa_settings
    settings.assistant_status = "IDLE"
    settings.instruction = ""
    settings.last_user_message = ""
    settings.last_assistant_message = "我已准备好。请告诉我你想怎样调整场景。"
    provider = bpy.context.window_manager.bsa_provider_session
    provider.show_provider_settings = True
    provider.api_base = "https://api.openai.com/v1"
    provider.model = "scene-planner-test"
    provider.api_key = ""
    provider.connection_status = "NOT_TESTED"
    provider.connection_message = "尚未测试连接"

    window = bpy.context.window
    screen = window.screen
    view_area = next((area for area in screen.areas if area.type == "VIEW_3D"), None)
    if view_area is None:
        raise AssertionError("当前工作区没有 3D 视图")
    window_region = next(
        (region for region in view_area.regions if region.type == "WINDOW"), None
    )
    if window_region is None:
        raise AssertionError("当前 3D 视图没有窗口区域")

    view_area.spaces.active.show_region_ui = False
    window.cursor_warp(
        window_region.x + window_region.width - 74,
        window_region.y + 110,
    )
    with bpy.context.temp_override(
        window=window,
        screen=screen,
        area=view_area,
        region=window_region,
    ):
        if bpy.ops.bsa.open_assistant("INVOKE_DEFAULT") != {"RUNNING_MODAL"}:
            raise AssertionError("助手形象对应的打开操作失败")

    print("BSA_UI_POPOVER_OPENED=true")
    bpy.app.timers.register(capture, first_interval=2.0)


def capture() -> None:
    """浮层完成绘制后保存整个 Blender 窗口。"""

    SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.screen.screenshot(filepath=str(SCREENSHOT_PATH), check_existing=False)
    print(f"BSA_UI_SCREENSHOT={SCREENSHOT_PATH}")
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(prepare, first_interval=1.0)
