"""在 Blender 4.5 后台验证外壳预览创建、校验和回滚。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bsa.application.enclosure_service import EnclosurePreviewService  # noqa: E402
from bsa.blender_adapter.enclosure_port import (  # noqa: E402
    BlenderEnclosurePreviewPort,
    TRANSACTION_ID_PROPERTY,
)
from bsa.core.enclosure import design_enclosure  # noqa: E402
from bsa.domain.enclosure import (  # noqa: E402
    BoardSpec,
    EnclosureParameters,
    MountingHoleSpec,
    RectangularPortSpec,
)
from bsa.domain.enclosure_preview import (  # noqa: E402
    EnclosurePartState,
    EnclosurePreviewPlan,
)


def board() -> BoardSpec:
    return BoardSpec(
        board_id="synthetic-demo-board",
        width_mm=70.0,
        depth_mm=50.0,
        height_mm=12.0,
        mounting_holes=(
            MountingHoleSpec("h1", 5.0, 5.0, 3.2),
            MountingHoleSpec("h2", 65.0, 5.0, 3.2),
            MountingHoleSpec("h3", 65.0, 45.0, 3.2),
            MountingHoleSpec("h4", 5.0, 45.0, 3.2),
        ),
        ports=(RectangularPortSpec("usb", "front", 35.0, 1.0, 12.0, 6.0),),
    )


def parameters() -> EnclosureParameters:
    return EnclosureParameters(
        wall_thickness_mm=2.0,
        floor_thickness_mm=2.0,
        lid_thickness_mm=2.0,
        board_clearance_xy_mm=1.0,
        top_clearance_mm=3.0,
        boss_height_mm=4.0,
        boss_outer_diameter_mm=6.0,
        screw_hole_diameter_mm=2.6,
        port_clearance_mm=0.5,
        corner_radius_mm=2.0,
    )


def plan(plan_id: str) -> EnclosurePreviewPlan:
    return EnclosurePreviewPlan(
        schema_version="0.1",
        plan_id=plan_id,
        source="blender_integration_test",
        requires_confirmation=True,
        enclosure_id="demo-enclosure",
        design=design_enclosure(board(), parameters()),
        user_summary="创建 70×50 毫米电路板外壳装配预览",
    )


class TamperedReadPort(BlenderEnclosurePreviewPort):
    """只篡改回读结果，用于证明真实 Blender 创建会被回滚。"""

    def read_created_parts(
        self, transaction_id: str
    ) -> tuple[EnclosurePartState, ...]:
        states = list(super().read_created_parts(transaction_id))
        for index, state in enumerate(states):
            if state.part_id == "lid":
                states[index] = replace(
                    state,
                    dimensions_mm=(
                        state.dimensions_mm[0] + 1.0,
                        state.dimensions_mm[1],
                        state.dimensions_mm[2],
                    ),
                )
        return tuple(states)


def create_existing_reference() -> object:
    mesh = bpy.data.meshes.new("ExistingReferenceMesh")
    mesh.from_pydata(
        [(-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.0, 0.5, 0.5)],
        [],
        [(0, 1, 2)],
    )
    obj = bpy.data.objects.new("ExistingReference", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (2.0, 3.0, 4.0)
    return obj


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.unit_settings.scale_length = 1.0
    existing = create_existing_reference()
    existing_matrix = existing.matrix_world.copy()

    failed = EnclosurePreviewService(TamperedReadPort(scene)).execute_plan(
        plan("preview-rollback"), confirmed=True
    )
    assert failed.status == "ROLLED_BACK", failed.to_dict()
    assert failed.rollback_verified is True
    assert existing.matrix_world == existing_matrix
    assert not any(
        str(obj.get(TRANSACTION_ID_PROPERTY, "")) == "preview-rollback"
        for obj in scene.objects
    )

    created = EnclosurePreviewService(BlenderEnclosurePreviewPort(scene)).execute_plan(
        plan("preview-success"), confirmed=True
    )
    assert created.status == "COMMITTED", created.to_dict()
    assert created.verification and created.verification.passed
    states = BlenderEnclosurePreviewPort(scene).read_created_parts("preview-success")
    assert len(states) == 12
    indexed = {state.part_id: state for state in states}
    assert max(
        abs(left - right)
        for left, right in zip(
            indexed["base_floor"].dimensions_mm, (76.0, 56.0, 2.0), strict=True
        )
    ) < 1e-5
    assert existing.matrix_world == existing_matrix

    output = os.environ.get("BSA_ENCLOSURE_PREVIEW_OUTPUT", "").strip()
    if output:
        existing_mesh = existing.data
        bpy.data.objects.remove(existing, do_unlink=True)
        if existing_mesh.users == 0:
            bpy.data.meshes.remove(existing_mesh)
        for obj in scene.objects:
            obj.select_set(
                str(obj.get(TRANSACTION_ID_PROPERTY, "")) == "preview-success"
            )
        selected = [obj for obj in scene.objects if obj.select_get()]
        if selected:
            bpy.context.view_layer.objects.active = selected[0]
        bpy.ops.wm.save_as_mainfile(filepath=output)

    print(
        "BSA_ENCLOSURE_PREVIEW_RESULT="
        + json.dumps(
            {
                "status": created.status,
                "rollback_status": failed.status,
                "part_count": len(states),
                "outer_size_mm": [76.0, 56.0, 23.0],
                "output": output or None,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
