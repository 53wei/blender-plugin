"""Blender background-mode M1 smoke suite.

Run with:
blender --background --factory-startup --python tests/integration/run_m1_suite.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import bpy

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from bsa.application.service import SceneEditingService  # noqa: E402
from bsa.blender_adapter.ids import ensure_stable_ids, stable_id  # noqa: E402
from bsa.blender_adapter.scene_port import BlenderScenePort  # noqa: E402
from bsa.core.fingerprint import fingerprint_snapshot  # noqa: E402
from bsa.core.validator import relevant_object_ids  # noqa: E402
from bsa.domain.actions import (  # noqa: E402
    ActionPlan,
    LockAction,
    PlaceOnAction,
    PreserveTransformConstraint,
)


def add_cube(name: str, location: tuple[float, float, float], scale: tuple[float, float, float]):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.context.view_layer.update()
    return obj


def main() -> int:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    desk = add_cube("Desk", (0.0, 0.0, 0.5), (2.0, 1.0, 0.5))
    lamp = add_cube("Lamp", (0.0, 0.0, 0.5), (0.2, 0.2, 0.5))
    add_cube("Chair", (4.0, 0.0, 0.5), (0.5, 0.5, 0.5))
    ensure_stable_ids(bpy.context.scene.objects)

    plan = ActionPlan(
        schema_version="0.1",
        plan_id="m1-blender-001",
        source="test",
        scene_fingerprint="",
        requires_confirmation=False,
        actions=(
            PlaceOnAction(
                action_id="place-1",
                object_id=stable_id(lamp),
                target_id=stable_id(desk),
                region="right",
                clearance=0.0,
            ),
            LockAction(action_id="lock-1", object_id=stable_id(desk)),
        ),
        constraints=(
            PreserveTransformConstraint(
                constraint_id="preserve-1", object_id=stable_id(desk)
            ),
        ),
        user_summary="Place Lamp on right side of Desk and lock Desk",
    )
    port = BlenderScenePort(bpy.context.scene)
    plan = replace(
        plan,
        scene_fingerprint=fingerprint_snapshot(port.read_snapshot(), relevant_object_ids(plan)),
    )
    result = SceneEditingService(port).execute_plan(plan)
    report = {
        "environment": {
            "blender_version": bpy.app.version_string,
            "blender_version_tuple": list(bpy.app.version),
            "background": bpy.app.background,
        },
        "case_id": "m1-blender-001",
        "result": result.to_dict(),
    }
    output = REPOSITORY_ROOT / "benchmarks" / "results" / "m1_blender_results.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("BSA_M1_RESULT=" + json.dumps(report, ensure_ascii=True))
    return 0 if result.status == "COMMITTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
