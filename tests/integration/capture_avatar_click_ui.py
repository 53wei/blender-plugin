"""通过真实 Windows 鼠标事件点击助手入口并保存验收图。"""

from __future__ import annotations

import ctypes
from pathlib import Path

import bpy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_PATH = REPOSITORY_ROOT / "docs" / "images" / "ui_0_4_0_click.png"
CLICK_X = 0
CLICK_Y = 0


def prepare() -> None:
    """准备计划并计算 GPU 形象与 Gizmo 共用的窗口坐标。"""

    if not hasattr(bpy.types.Scene, "bsa_settings"):
        raise AssertionError("已安装扩展未启用")
    settings = bpy.context.scene.bsa_settings
    settings.instruction = "把 Lamp 放到 Desk 右侧，并锁定 Desk"
    if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
        raise AssertionError("生成预览失败")

    view_area = next(
        (area for area in bpy.context.screen.areas if area.type == "VIEW_3D"), None
    )
    if view_area is None:
        raise AssertionError("当前工作区没有 3D 视图")
    view_area.spaces.active.show_region_ui = False
    region = next(
        (item for item in view_area.regions if item.type == "WINDOW"), None
    )
    if region is None:
        raise AssertionError("当前 3D 视图没有窗口区域")

    global CLICK_X, CLICK_Y
    CLICK_X = int(region.x + region.width - 74)
    CLICK_Y = int(region.y + 74)
    bpy.app.timers.register(press_avatar, first_interval=1.0)
    bpy.app.timers.register(release_avatar, first_interval=1.3)
    bpy.app.timers.register(press_avatar, first_interval=2.0)
    bpy.app.timers.register(release_avatar, first_interval=2.3)
    bpy.app.timers.register(capture, first_interval=5.0)


def press_avatar() -> None:
    """在助手中心按下鼠标左键。"""

    bpy.context.window.cursor_warp(CLICK_X, CLICK_Y)
    user32 = ctypes.windll.user32
    user32.SetCursorPos(CLICK_X, bpy.context.window.height - CLICK_Y)
    user32.mouse_event(0x0002, 0, 0, 0, 0)


def release_avatar() -> None:
    """让 Blender 先处理按下事件，再抬起鼠标左键。"""

    user32 = ctypes.windll.user32
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    print(f"BSA_AVATAR_CLICK={CLICK_X},{CLICK_Y}")


def capture() -> None:
    """点击响应完成后保存整窗结果。"""

    SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.screen.screenshot(filepath=str(SCREENSHOT_PATH), check_existing=False)
    print(f"BSA_AVATAR_CLICK_SCREENSHOT={SCREENSHOT_PATH}")
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(prepare, first_interval=1.0)
