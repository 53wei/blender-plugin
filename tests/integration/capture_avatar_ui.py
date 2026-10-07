"""在 Blender 图形窗口中单独截取 0.4.0 视口助手入口。"""

from __future__ import annotations

from pathlib import Path

import bpy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_PATH = REPOSITORY_ROOT / "docs" / "images" / "ui_0_4_0_avatar.png"


def prepare() -> None:
    """保持助手待机并隐藏侧栏，让实体入口清晰可见。"""

    if not hasattr(bpy.types.Scene, "bsa_settings"):
        raise AssertionError("已安装扩展未启用")
    view_area = next(
        (area for area in bpy.context.screen.areas if area.type == "VIEW_3D"), None
    )
    if view_area is None:
        raise AssertionError("当前工作区没有 3D 视图")
    view_area.spaces.active.show_region_ui = False
    bpy.context.scene.bsa_settings.assistant_status = "IDLE"
    bpy.app.timers.register(capture, first_interval=2.0)


def capture() -> None:
    """保存带待机助手入口的整个 Blender 窗口。"""

    SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.screen.screenshot(filepath=str(SCREENSHOT_PATH), check_existing=False)
    print(f"BSA_AVATAR_SCREENSHOT={SCREENSHOT_PATH}")
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(prepare, first_interval=1.0)
