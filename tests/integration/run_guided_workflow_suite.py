"""Blender background checks for the guided model-place-camera workflow.

Run with:
blender --background --factory-startup --python-exit-code 1 \
  --python tests/integration/run_guided_workflow_suite.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from bsa.application.guided_workflow import GuidedWorkflowPlanBuilder  # noqa: E402
from bsa.application.service import SceneEditingService  # noqa: E402
from bsa.blender_adapter.camera_controller import apply_camera_frame_plan  # noqa: E402
from bsa.blender_adapter.ids import ensure_stable_ids, stable_id  # noqa: E402
from bsa.blender_adapter.scene_port import BlenderScenePort  # noqa: E402
from bsa.core.camera_framing import build_camera_frame_plan  # noqa: E402


def add_cube(name: str, location: tuple[float, float, float]) -> object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def execute(plan, port: BlenderScenePort) -> None:
    result = SceneEditingService(port).execute_plan(plan, confirmed=True)
    if result.status != "COMMITTED" or not result.verification or not result.verification.passed:
        raise AssertionError(result.to_dict())


def main() -> int:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    objects = (
        add_cube("Model_A", (-3.0, 0.0, 2.0)),
        add_cube("Model_B", (0.0, 1.0, 1.0)),
        add_cube("Model_C", (3.0, -1.0, 1.5)),
    )
    ensure_stable_ids(objects)
    object_ids = tuple(stable_id(obj) for obj in objects)
    port = BlenderScenePort(bpy.context.scene)
    builder = GuidedWorkflowPlanBuilder()

    execute(builder.ground(port.read_snapshot(), object_ids), port)
    execute(builder.grid(port.read_snapshot(), object_ids, columns=2, gap=0.25), port)
    execute(
        builder.rotate(
            port.read_snapshot(),
            (object_ids[0],),
            axis="z",
            angle_degrees=45.0,
        ),
        port,
    )
    execute(builder.scale(port.read_snapshot(), (object_ids[1],), factor=1.25), port)
    execute(builder.ground(port.read_snapshot(), object_ids), port)

    snapshot = port.read_snapshot()
    camera_plan = build_camera_frame_plan(
        snapshot,
        object_ids,
        lens_mm=50.0,
        aspect_ratio=16 / 9,
        margin=0.12,
    )
    camera = apply_camera_frame_plan(bpy.context.scene, camera_plan)
    if bpy.context.scene.camera != camera or camera.type != "CAMERA":
        raise AssertionError("Guided camera was not applied")

    after = port.read_snapshot().object_map()
    report = {
        "blender_version": bpy.app.version_string,
        "objects": len(object_ids),
        "all_grounded": all(
            abs(after[object_id].bbox_world.min_xyz[2]) < 1e-4
            for object_id in object_ids
        ),
        "camera_created": bpy.context.scene.camera is not None,
        "lens_mm": float(camera.data.lens),
    }
    if not report["all_grounded"]:
        raise AssertionError(report)
    output = REPOSITORY_ROOT / "benchmarks" / "results" / "guided_workflow.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("BSA_GUIDED_WORKFLOW_RESULT=" + json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
