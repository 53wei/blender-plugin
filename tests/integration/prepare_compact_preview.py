"""打开专用演示窗口的简洁助手，不联网、不执行、不保存工程。"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/desk_lamp_demo.blend"
if "--factory-startup" not in sys.argv or Path(bpy.data.filepath).resolve() != FIXTURE.resolve():
    raise RuntimeError("演示启动仅允许出厂设置和固定演示夹具")


def prepare() -> None:
    """只准备输入和侧栏；用户需要亲自生成计划并确认执行。"""
    import addon_utils

    addon_utils.enable("bl_ext.user_default.blender_scene_assistant", default_set=False)
    before = {obj.name: tuple(v for row in obj.matrix_world for v in row)
              for obj in bpy.context.scene.objects}
    bpy.ops.bsa.clear()
    settings = bpy.context.scene.bsa_settings
    provider = bpy.context.window_manager.bsa_provider_session
    settings.instruction = "把 Lamp 放到 Desk 右侧"
    provider.show_settings = False
    provider.api_key = ""
    provider.model = ""
    area = next(area for area in bpy.context.window.screen.areas if area.type == "VIEW_3D")
    area.spaces.active.show_region_ui = True
    area.tag_redraw()
    assert before == {obj.name: tuple(v for row in obj.matrix_world for v in row)
                      for obj in bpy.context.scene.objects}
    assert settings.assistant_status == "IDLE" and not settings.plan_json
    bpy.app.timers.register(show_sidebar, first_interval=0.5)


def show_sidebar() -> None:
    area = next(area for area in bpy.context.window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "UI")
    region.active_panel_category = "BSA"
    area.tag_redraw()
    print("BSA_COMPACT_PREVIEW_READY=IDLE; no network, no execution, no save", flush=True)


bpy.app.timers.register(prepare, first_interval=0.75)
