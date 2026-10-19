"""在 Blender 4.5 后台验证转接板真实网格、孔测量和失败回滚。"""

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

from bsa.application.adapter_plate_service import (  # noqa: E402
    AdapterPlateCreationService,
    AdapterPlateUpdateService,
)
from bsa.blender_adapter.adapter_plate_port import (  # noqa: E402
    BlenderAdapterPlatePort,
    PLATE_ID_PROPERTY,
    TRANSACTION_ID_PROPERTY,
)
from bsa.core.adapter_plate import design_adapter_plate, resize_adapter_plate  # noqa: E402
from bsa.domain.adapter_plate import (  # noqa: E402
    AdapterPlateResizePatch,
    AdapterPlateSpec,
    MountingPatternSpec,
    PatternHoleSpec,
)
from bsa.domain.adapter_plate_mesh import (  # noqa: E402
    AdapterPlateCreationPlan,
    AdapterPlateMeshState,
    AdapterPlateUpdatePlan,
)


def plate_spec() -> AdapterPlateSpec:
    return AdapterPlateSpec(
        plate_id="adapter-demo",
        width_mm=80.0,
        depth_mm=40.0,
        thickness_mm=3.0,
        corner_radius_mm=2.0,
        mounting_patterns=(
            MountingPatternSpec(
                "device",
                20.0,
                20.0,
                (
                    PatternHoleSpec("device-left", -10.0, 0.0, 3.2),
                    PatternHoleSpec("device-right", 10.0, 0.0, 3.2),
                ),
            ),
            MountingPatternSpec(
                "support",
                40.0,
                20.0,
                (
                    PatternHoleSpec("support-front", 0.0, -10.0, 4.2),
                    PatternHoleSpec("support-back", 0.0, 10.0, 4.2),
                ),
            ),
        ),
    )


def plan(plan_id: str) -> AdapterPlateCreationPlan:
    return AdapterPlateCreationPlan(
        schema_version="0.1",
        plan_id=plan_id,
        source="blender_integration_test",
        requires_confirmation=True,
        plate_id="adapter-demo",
        design=design_adapter_plate(plate_spec()),
        user_summary="创建 80×40×3 毫米四孔转接板",
    )


class TamperedReadPort(BlenderAdapterPlatePort):
    def read_created_plates(
        self,
        transaction_id: str,
    ) -> tuple[AdapterPlateMeshState, ...]:
        states = list(super().read_created_plates(transaction_id))
        if states and states[0].measured_holes:
            first = states[0]
            states[0] = replace(
                first,
                measured_holes=(
                    replace(first.measured_holes[0], diameter_mm=99.0),
                    *first.measured_holes[1:],
                ),
            )
        return tuple(states)


class ExtraObjectPort(BlenderAdapterPlatePort):
    """注入同事务额外对象，证明对象白名单不是只数网格。"""

    def create_adapter_plate(self, plate_id, transaction_id, spec) -> None:
        super().create_adapter_plate(plate_id, transaction_id, spec)
        extra = bpy.data.objects.new("InjectedExtraObject", None)
        extra[PLATE_ID_PROPERTY] = plate_id
        extra[TRANSACTION_ID_PROPERTY] = transaction_id
        bpy.context.scene.collection.objects.link(extra)


class TamperedUpdateReadPort(BlenderAdapterPlatePort):
    """只篡改更新后的回读，证明失败会恢复旧网格。"""

    def read_plate(self, plate_id: str) -> tuple[AdapterPlateMeshState, ...]:
        states = list(super().read_plate(plate_id))
        if states and states[0].transaction_id == "adapter-update-rollback":
            first = states[0]
            states[0] = replace(
                first,
                measured_holes=(
                    replace(first.measured_holes[0], diameter_mm=99.0),
                    *first.measured_holes[1:],
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


def update_plan(plan_id: str, before, after) -> AdapterPlateUpdatePlan:
    return AdapterPlateUpdatePlan(
        schema_version="0.1",
        plan_id=plan_id,
        source="blender_integration_test",
        requires_confirmation=True,
        plate_id=before.plate_id,
        before_design=before,
        design=after,
        user_summary="板宽改为 90 mm；孔的世界位置保持不变",
    )


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.unit_settings.scale_length = 1.0
    existing = create_existing_reference()
    existing_matrix = existing.matrix_world.copy()

    extra_failed = AdapterPlateCreationService(ExtraObjectPort(scene)).execute_plan(
        plan("adapter-extra-object"),
        confirmed=True,
    )
    assert extra_failed.status == "ROLLED_BACK", extra_failed.to_dict()
    assert extra_failed.rollback_verified is True
    assert existing.matrix_world == existing_matrix

    failed = AdapterPlateCreationService(TamperedReadPort(scene)).execute_plan(
        plan("adapter-rollback"),
        confirmed=True,
    )
    assert failed.status == "ROLLED_BACK", failed.to_dict()
    assert failed.rollback_verified is True
    assert existing.matrix_world == existing_matrix
    assert not any(
        str(obj.get(TRANSACTION_ID_PROPERTY, "")) == "adapter-rollback"
        for obj in scene.objects
    )

    created = AdapterPlateCreationService(BlenderAdapterPlatePort(scene)).execute_plan(
        plan("adapter-success"),
        confirmed=True,
    )
    assert created.status == "COMMITTED", created.to_dict()
    assert created.verification and created.verification.passed
    states = BlenderAdapterPlatePort(scene).read_created_plates("adapter-success")
    assert len(states) == 1
    state = states[0]
    assert state.is_manifold
    assert state.connected_components == 1
    assert state.through_hole_count == 4
    assert max(
        abs(left - right)
        for left, right in zip(state.size_mm, (80.0, 40.0, 3.0), strict=True)
    ) < 0.02
    assert abs(state.corner_radius_mm - 2.0) < 0.02
    assert existing.matrix_world == existing_matrix

    port = BlenderAdapterPlatePort(scene)
    before_update = port.read_plate_design("adapter-demo")
    revision = resize_adapter_plate(
        plate_spec(),
        AdapterPlateResizePatch(
            new_width_mm=90.0,
            new_depth_mm=None,
            fixed_x_edge="right",
            fixed_y_edge="front",
            preserve_pattern_ids=("device", "support"),
        ),
        origin_offset_mm=before_update.origin_offset_mm,
    )
    failed_update = AdapterPlateUpdateService(
        TamperedUpdateReadPort(scene)
    ).execute_plan(
        update_plan(
            "adapter-update-rollback",
            before_update,
            revision.design,
        ),
        confirmed=True,
    )
    assert failed_update.status == "ROLLED_BACK", failed_update.to_dict()
    assert failed_update.rollback_verified is True
    assert port.read_plate_design("adapter-demo") == before_update
    assert existing.matrix_world == existing_matrix

    updated = AdapterPlateUpdateService(port).execute_plan(
        update_plan("adapter-update-success", before_update, revision.design),
        confirmed=True,
    )
    assert updated.status == "COMMITTED", updated.to_dict()
    assert updated.verification and updated.verification.passed
    updated_state = port.read_plate("adapter-demo")[0]
    assert max(
        abs(left - right)
        for left, right in zip(
            updated_state.size_mm,
            (90.0, 40.0, 3.0),
            strict=True,
        )
    ) < 0.02
    assert existing.matrix_world == existing_matrix

    output = os.environ.get("BSA_ADAPTER_PLATE_OUTPUT", "").strip()
    if output:
        existing_mesh = existing.data
        bpy.data.objects.remove(existing, do_unlink=True)
        if existing_mesh.users == 0:
            bpy.data.meshes.remove(existing_mesh)
        bpy.ops.wm.save_as_mainfile(filepath=output)

    print(
        "BSA_ADAPTER_PLATE_RESULT="
        + json.dumps(
            {
                "status": created.status,
                "extra_object_rollback_status": extra_failed.status,
                "rollback_status": failed.status,
                "object_count": len(states),
                "size_mm": list(state.size_mm),
                "through_hole_count": state.through_hole_count,
                "is_manifold": state.is_manifold,
                "connected_components": state.connected_components,
                "vertex_count": state.vertex_count,
                "face_count": state.face_count,
                "output": output or None,
                "update_rollback_status": failed_update.status,
                "update_status": updated.status,
                "update_world_holes_preserved": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
