"""矩形转接板创建后安全更新、回滚与反向更新测试。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from bsa.application.adapter_plate_service import (
    AdapterPlateCreationService,
    AdapterPlateUpdateService,
)
from bsa.application.memory_adapter_plate import MemoryAdapterPlatePort
from bsa.core.adapter_plate import design_adapter_plate, resize_adapter_plate
from bsa.core.adapter_plate_mesh import adapter_plate_design_from_dict
from bsa.domain.adapter_plate import AdapterPlateResizePatch
from bsa.domain.adapter_plate_mesh import (
    AdapterPlateCreationPlan,
    AdapterPlateUpdatePlan,
)
from bsa.domain.errors import DomainError, ErrorCode
from tests.test_adapter_plate import make_plate


def create_plan() -> AdapterPlateCreationPlan:
    design = design_adapter_plate(make_plate())
    return AdapterPlateCreationPlan(
        schema_version="0.1",
        plan_id="create-before-update",
        source="test",
        requires_confirmation=True,
        plate_id=design.plate_id,
        design=design,
        user_summary="创建待修改转接板",
    )


def resize_revision(*, width: float = 90.0, origin=(0.0, 0.0, 0.0)):
    return resize_adapter_plate(
        make_plate(),
        AdapterPlateResizePatch(
            new_width_mm=width,
            new_depth_mm=None,
            fixed_x_edge="right",
            fixed_y_edge="front",
            preserve_pattern_ids=("device", "support"),
        ),
        origin_offset_mm=origin,
    )


def update_plan(
    *,
    plan_id: str = "update-001",
    before=None,
    after=None,
) -> AdapterPlateUpdatePlan:
    current = design_adapter_plate(make_plate()) if before is None else before
    revised = resize_revision().design if after is None else after
    return AdapterPlateUpdatePlan(
        schema_version="0.1",
        plan_id=plan_id,
        source="test",
        requires_confirmation=True,
        plate_id=current.plate_id,
        before_design=current,
        design=revised,
        user_summary="板宽改为 90 mm；所有孔的世界位置保持不变",
    )


def create_existing(port: MemoryAdapterPlatePort) -> None:
    result = AdapterPlateCreationService(port).execute_plan(
        create_plan(),
        confirmed=True,
    )
    if result.status != "COMMITTED":
        raise AssertionError(result)


def world_holes(design):
    return {
        hole.hole_id: (
            hole.center_mm[0] + design.origin_offset_mm[0],
            hole.center_mm[1] + design.origin_offset_mm[1],
        )
        for hole in design.holes
    }


class AdapterPlateUpdateServiceTests(unittest.TestCase):
    def test_saved_design_metadata_requires_real_string_identifiers(self) -> None:
        payload = design_adapter_plate(make_plate()).to_dict()
        payload["plate_id"] = 123
        with self.assertRaisesRegex(DomainError, "plate_id"):
            adapter_plate_design_from_dict(payload)

        payload = design_adapter_plate(make_plate()).to_dict()
        payload["holes"][0]["hole_id"] = 456
        with self.assertRaisesRegex(DomainError, "hole_id"):
            adapter_plate_design_from_dict(payload)

    def test_update_requires_confirmation_and_keeps_scene_unchanged(self) -> None:
        port = MemoryAdapterPlatePort(existing_objects={"fixture": (1.0, 2.0, 3.0)})
        create_existing(port)
        before = port.scene_state()
        result = AdapterPlateUpdateService(port).execute_plan(update_plan())
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.PRECONDITION_FAILED)
        self.assertEqual(port.scene_state(), before)

    def test_confirmed_update_replaces_mesh_and_preserves_world_holes(self) -> None:
        port = MemoryAdapterPlatePort(existing_objects={"fixture": (1.0, 2.0, 3.0)})
        create_existing(port)
        before_design = port.read_plate_design("adapter-demo")
        result = AdapterPlateUpdateService(port).execute_plan(
            update_plan(before=before_design),
            confirmed=True,
        )
        self.assertEqual(result.status, "COMMITTED")
        self.assertTrue(result.verification and result.verification.passed)
        after_design = port.read_plate_design("adapter-demo")
        self.assertEqual(after_design.size_mm, (90.0, 40.0, 3.0))
        self.assertEqual(after_design.origin_offset_mm, (-10.0, 0.0, 0.0))
        self.assertEqual(world_holes(after_design), world_holes(before_design))
        self.assertEqual(port.existing_objects, {"fixture": (1.0, 2.0, 3.0)})
        states = port.read_plate("adapter-demo")
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].transaction_id, "update-001")

    def test_stale_before_design_is_rejected_before_checkpoint(self) -> None:
        port = MemoryAdapterPlatePort()
        create_existing(port)
        before = port.scene_state()
        stale = replace(
            design_adapter_plate(make_plate()),
            origin_offset_mm=(1.0, 0.0, 0.0),
        )
        stale_after = replace(
            resize_revision().design,
            origin_offset_mm=(-9.0, 0.0, 0.0),
        )
        result = AdapterPlateUpdateService(port).execute_plan(
            update_plan(before=stale, after=stale_after),
            confirmed=True,
        )
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.PLAN_STALE)
        self.assertEqual(port.update_checkpoint_count, 0)
        self.assertEqual(port.scene_state(), before)

    def test_update_cannot_reassign_a_hole_to_another_pattern(self) -> None:
        port = MemoryAdapterPlatePort()
        create_existing(port)
        before = port.read_plate_design("adapter-demo")
        revised = resize_revision(origin=before.origin_offset_mm).design
        holes = list(revised.holes)
        holes[0] = replace(holes[0], pattern_id="support")
        tampered = replace(revised, holes=tuple(holes))

        result = AdapterPlateUpdateService(port).execute_plan(
            update_plan(before=before, after=tampered),
            confirmed=True,
        )

        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(
            result.errors[0].code,
            ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
        )
        self.assertEqual(port.update_checkpoint_count, 0)

    def test_invalid_mesh_or_unauthorized_change_rolls_back(self) -> None:
        for tamper, code in (
            ("hole_diameter", ErrorCode.POSTCONDITION_FAILED),
            ("existing_scene", ErrorCode.UNAUTHORIZED_CHANGE),
        ):
            with self.subTest(tamper=tamper):
                port = MemoryAdapterPlatePort(
                    existing_objects={"fixture": (1.0, 2.0, 3.0)}
                )
                create_existing(port)
                before = port.scene_state()
                port.update_tamper = tamper
                result = AdapterPlateUpdateService(port).execute_plan(
                    update_plan(before=port.read_plate_design("adapter-demo")),
                    confirmed=True,
                )
                self.assertEqual(result.status, "ROLLED_BACK")
                self.assertTrue(result.rollback_verified)
                self.assertEqual(result.errors[0].code, code)
                self.assertEqual(port.scene_state(), before)

    def test_reverse_update_restores_previous_design(self) -> None:
        port = MemoryAdapterPlatePort()
        create_existing(port)
        original = port.read_plate_design("adapter-demo")
        forward = resize_revision(origin=original.origin_offset_mm)
        first = AdapterPlateUpdateService(port).execute_plan(
            update_plan(before=original, after=forward.design),
            confirmed=True,
        )
        self.assertEqual(first.status, "COMMITTED")
        reverse = resize_adapter_plate(
            forward.updated_spec,
            AdapterPlateResizePatch(
                new_width_mm=80.0,
                new_depth_mm=None,
                fixed_x_edge="right",
                fixed_y_edge="front",
                preserve_pattern_ids=("device", "support"),
            ),
            origin_offset_mm=forward.design.origin_offset_mm,
        )
        second = AdapterPlateUpdateService(port).execute_plan(
            update_plan(
                plan_id="undo-001",
                before=forward.design,
                after=reverse.design,
            ),
            confirmed=True,
        )
        self.assertEqual(second.status, "COMMITTED")
        self.assertEqual(port.read_plate_design("adapter-demo"), original)


if __name__ == "__main__":
    unittest.main()
