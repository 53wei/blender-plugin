"""在真实 Blender 窗口中保存 0.6.0 AI 数据确认界面。"""

from __future__ import annotations

from pathlib import Path

import bpy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_PATH = REPOSITORY_ROOT / "docs" / "images" / "ui_0_6_0_ai_review.png"


def add_cube(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
) -> None:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.context.view_layer.update()


def prepare() -> None:
    if not hasattr(bpy.types.Scene, "bsa_settings"):
        raise AssertionError("已安装扩展未启用")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    add_cube("Desk", (0.0, 0.0, 0.5), (2.0, 1.0, 0.5))
    add_cube("Lamp", (0.0, 0.0, 0.5), (0.2, 0.2, 0.5))

    settings = bpy.context.scene.bsa_settings
    provider = bpy.context.window_manager.bsa_provider_session
    provider.show_provider_settings = False
    provider.api_base = "https://api.example.com/v1"
    provider.model = "scene-planner"
    provider.api_key = ""
    settings.instruction = "重新安排 Lamp 和 Desk，让画面更紧凑"
    if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
        raise AssertionError("AI 数据确认界面准备失败")
    if settings.assistant_status != "AI_REVIEW":
        raise AssertionError("助手没有进入 AI 数据确认状态")

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
            raise AssertionError("无法打开场景领航员浮层")

    bpy.app.timers.register(capture, first_interval=2.0)


def capture() -> None:
    SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.screen.screenshot(filepath=str(SCREENSHOT_PATH), check_existing=False)
    print(f"BSA_AI_REVIEW_SCREENSHOT={SCREENSHOT_PATH}")
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(prepare, first_interval=1.0)
