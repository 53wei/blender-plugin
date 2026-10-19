"""在一次性 Blender 窗口中截取转接板输入和确认界面，不保存工程。"""

from __future__ import annotations

import importlib.util
import importlib
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / ".impeccable" / "review"
extension = None
object_count = 0
ARGS = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
CASE = ARGS[0] if ARGS else "start"
if CASE not in {"start", "input", "review", "questions"}:
    raise RuntimeError("界面截图案例只支持 start、input、review 或 questions")


def load_extension():
    module_name = "blender_scene_assistant_adapter_plate_capture"
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


def prepare() -> None:
    global extension, object_count
    if "--factory-startup" not in sys.argv or bpy.data.filepath:
        raise RuntimeError("界面截图只允许出厂启动的空工程")
    extension = load_extension()
    extension.register()
    object_count = len(bpy.context.scene.objects)
    if CASE in {"input", "review"}:
        assert bpy.ops.bsa.manual_adapter_plate() == {"FINISHED"}
    if CASE == "review":
        assert bpy.ops.bsa.review_adapter_plate() == {"FINISHED"}
        assert len(bpy.context.scene.objects) == object_count
    if CASE == "questions":
        operators = importlib.import_module(
            "blender_scene_assistant_adapter_plate_capture.bsa.ui.adapter_plate_operators"
        )
        WorkerOutcome = importlib.import_module(
            "blender_scene_assistant_adapter_plate_capture.bsa.infra.provider_process"
        ).WorkerOutcome
        candidate = {
            "schema_version": "0.1",
            "status": "needs_input",
            "part_family": "adapter_plate",
            "missing_measurements": [
                {
                    "measurement_id": "plate_size",
                    "measurement_type": "outer_width",
                    "target_id": "adapter_plate",
                    "label": "可用板宽与板深",
                    "reason": "确认外形能放入安装位置，并保留孔到边缘距离",
                    "unit": "mm",
                },
                {
                    "measurement_id": "hole_patterns",
                    "measurement_type": "hole_center_x",
                    "target_id": "device_and_support",
                    "label": "两侧孔中心、孔距和孔径",
                    "reason": "让设备孔和支架孔真实对齐",
                    "unit": "mm",
                },
            ],
            "assumptions": [],
            "user_summary": "先补充影响装配的关键尺寸",
        }
        operators._apply_print_ai_outcome(
            bpy.context.scene.bsa_adapter_plate_settings,
            bpy.context.window_manager.bsa_provider_session,
            WorkerOutcome(
                True,
                result={
                    "plan_payload": candidate,
                    "usage": {},
                    "request_count": 1,
                    "repair_count": 0,
                },
            ),
        )
    area = next(area for area in bpy.context.window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    with bpy.context.temp_override(
        window=bpy.context.window,
        area=area,
        region=region,
    ):
        assert bpy.ops.bsa.launch_assistant() == {"FINISHED"}
    area.tag_redraw()
    bpy.app.timers.register(capture, first_interval=1.0)


def capture() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.screen.screenshot(
        filepath=str(OUTPUT / f"adapter_plate_{CASE}.png"),
        check_existing=False,
    )
    settings = bpy.context.scene.bsa_adapter_plate_settings
    expected = "AI_NEEDS_INPUT" if CASE == "questions" else CASE.upper()
    assert settings.stage == expected
    assert len(bpy.context.scene.objects) == object_count
    print(
        f"BSA_ADAPTER_PLATE_CAPTURE={CASE}; no network, no scene mutation",
        flush=True,
    )
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(prepare, first_interval=0.5)

