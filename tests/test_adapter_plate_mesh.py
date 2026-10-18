"""矩形转接板 P1 网格计划、独立验证与创建事务。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from bsa.application.adapter_plate_service import AdapterPlateCreationService
from bsa.application.memory_adapter_plate import MemoryAdapterPlatePort
from bsa.core.adapter_plate import design_adapter_plate
from bsa.core.adapter_plate_mesh import (
    build_adapter_plate_mesh_spec,
    verify_adapter_plate_mesh,
)
from bsa.domain.adapter_plate_mesh import AdapterPlateCreationPlan
from bsa.domain.errors import DomainError, ErrorCode
from tests.test_adapter_plate import make_plate


def make_plan(*, plan_id: str = "adapter-create-001") -> AdapterPlateCreationPlan:
    return AdapterPlateCreationPlan(
        schema_version="0.1",
        plan_id=plan_id,
        source="test",
        requires_confirmation=True,
        plate_id="adapter-demo",
        design=design_adapter_plate(make_plate()),
        user_summary="创建四孔矩形转接板",
    )


class CheckpointFailurePort(MemoryAdapterPlatePort):
    def capture_creation_checkpoint(self, transaction_id: str):
        del transaction_id
        raise RuntimeError("injected checkpoint failure")


class RollbackFailurePort(MemoryAdapterPlatePort):
    def restore_creation_checkpoint(self, checkpoint, transaction_id: str) -> bool:
        del checkpoint, transaction_id
        raise RuntimeError("injected rollback failure")


class AdapterPlateMeshSpecTests(unittest.TestCase):
    def test_mesh_spec_contains_exact_plate_and_hole_geometry(self) -> None:
        spec = build_adapter_plate_mesh_spec(make_plan().design)
        self.assertEqual(spec.size_mm, (80.0, 40.0, 3.0))
        self.assertEqual(spec.corner_radius_mm, 2.0)
        self.assertEqual(spec.origin_offset_mm, (0.0, 0.0, 0.0))
        self.assertEqual(spec.outer_corner_segments, 8)
        self.assertEqual(spec.hole_segments, 32)
        self.assertEqual(len(spec.holes), 4)
        self.assertEqual(spec.holes[0].center_mm, (10.0, 20.0))

    def test_handcrafted_invalid_design_is_rejected_by_mesh_builder(self) -> None:
        invalid = replace(make_plan().design, size_mm=(20.0, 40.0, 3.0))
        with self.assertRaises(DomainError) as raised:
            build_adapter_plate_mesh_spec(invalid)
        self.assertEqual(raised.exception.code, ErrorCode.PRINT_SPEC_INVALID)

    def test_verifier_checks_measured_holes_not_only_metadata(self) -> None:
        spec = build_adapter_plate_mesh_spec(make_plan().design)
        port = MemoryAdapterPlatePort()
        checkpoint = port.capture_creation_checkpoint("direct")
        port.create_adapter_plate("adapter-demo", "direct", spec)
        actual = port.read_created_plates("direct")
        passed = verify_adapter_plate_mesh(
            spec,
            actual,
            plate_id="adapter-demo",
            transaction_id="direct",
            existing_scene_unchanged=port.existing_state_matches(checkpoint, "direct"),
        )
        self.assertTrue(passed.passed)

        tampered = replace(
            actual[0],
            measured_holes=(
                replace(actual[0].measured_holes[0], diameter_mm=99.0),
                *actual[0].measured_holes[1:],
            ),
        )
        failed = verify_adapter_plate_mesh(
            spec,
            (tampered,),
            plate_id="adapter-demo",
            transaction_id="direct",
            existing_scene_unchanged=True,
        )
        self.assertFalse(failed.passed)
        self.assertTrue(
            any(
                check.check_type == "through_hole_geometry" and not check.passed
                for check in failed.checks
            )
        )


class AdapterPlateCreationServiceTests(unittest.TestCase):
    def test_plan_requires_explicit_confirmation_before_creation(self) -> None:
        port = MemoryAdapterPlatePort(existing_objects={"fixture": (1.0, 2.0, 3.0)})
        before = port.scene_state()
        result = AdapterPlateCreationService(port).execute_plan(make_plan())
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.PRECONDITION_FAILED)
        self.assertEqual(port.scene_state(), before)

    def test_confirmed_plan_creates_one_verified_mesh(self) -> None:
        port = MemoryAdapterPlatePort(existing_objects={"fixture": (1.0, 2.0, 3.0)})
        result = AdapterPlateCreationService(port).execute_plan(
            make_plan(), confirmed=True
        )
        self.assertEqual(result.status, "COMMITTED")
        self.assertTrue(result.verification and result.verification.passed)
        states = port.read_created_plates("adapter-create-001")
        self.assertEqual(len(states), 1)
        self.assertTrue(states[0].is_manifold)
        self.assertEqual(states[0].through_hole_count, 4)
        self.assertEqual(port.existing_objects, {"fixture": (1.0, 2.0, 3.0)})

    def test_creation_failure_rolls_back_every_new_object(self) -> None:
        port = MemoryAdapterPlatePort(
            existing_objects={"fixture": (1.0, 2.0, 3.0)},
            fail_on_create=True,
        )
        before = port.scene_state()
        result = AdapterPlateCreationService(port).execute_plan(
            make_plan(), confirmed=True
        )
        self.assertEqual(result.status, "ROLLED_BACK")
        self.assertTrue(result.rollback_verified)
        self.assertEqual(result.errors[0].code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(port.scene_state(), before)

    def test_wrong_hole_or_non_manifold_mesh_rolls_back(self) -> None:
        for tamper in ("hole_diameter", "manifold", "extra_object"):
            with self.subTest(tamper=tamper):
                port = MemoryAdapterPlatePort(tamper=tamper)
                result = AdapterPlateCreationService(port).execute_plan(
                    make_plan(), confirmed=True
                )
                self.assertEqual(result.status, "ROLLED_BACK")
                self.assertEqual(
                    result.errors[0].code,
                    ErrorCode.POSTCONDITION_FAILED,
                )
                self.assertEqual(port.read_created_plates("adapter-create-001"), ())

    def test_existing_scene_change_is_unauthorized_and_rolls_back(self) -> None:
        port = MemoryAdapterPlatePort(
            existing_objects={"fixture": (1.0, 2.0, 3.0)},
            tamper="existing_scene",
        )
        before = port.scene_state()
        result = AdapterPlateCreationService(port).execute_plan(
            make_plan(), confirmed=True
        )
        self.assertEqual(result.status, "ROLLED_BACK")
        self.assertEqual(result.errors[0].code, ErrorCode.UNAUTHORIZED_CHANGE)
        self.assertEqual(port.scene_state(), before)

    def test_duplicate_plate_and_transaction_are_rejected_without_mutation(self) -> None:
        port = MemoryAdapterPlatePort()
        service = AdapterPlateCreationService(port)
        self.assertEqual(
            service.execute_plan(make_plan(), confirmed=True).status,
            "COMMITTED",
        )
        before = port.scene_state()
        duplicate_plate = replace(make_plan(plan_id="adapter-create-002"))
        duplicate_transaction = make_plan()
        for plan in (duplicate_plate, duplicate_transaction):
            with self.subTest(plan=plan):
                result = service.execute_plan(plan, confirmed=True)
                self.assertEqual(result.status, "REJECTED")
                self.assertEqual(result.errors[0].code, ErrorCode.PRECONDITION_FAILED)
                self.assertEqual(port.scene_state(), before)

    def test_invalid_plan_is_rejected_before_checkpoint(self) -> None:
        invalid_plans = (
            replace(make_plan(), schema_version="9.9"),
            replace(make_plan(), requires_confirmation=False),
            replace(make_plan(), design=None),  # type: ignore[arg-type]
        )
        for plan in invalid_plans:
            with self.subTest(plan=plan):
                port = MemoryAdapterPlatePort()
                result = AdapterPlateCreationService(port).execute_plan(
                    plan, confirmed=True
                )
                self.assertEqual(result.status, "REJECTED")
                self.assertEqual(result.errors[0].code, ErrorCode.PLAN_SCHEMA_INVALID)
                self.assertEqual(port.checkpoint_count, 0)

    def test_checkpoint_and_rollback_failures_are_explicit(self) -> None:
        checkpoint_result = AdapterPlateCreationService(
            CheckpointFailurePort()
        ).execute_plan(make_plan(), confirmed=True)
        self.assertEqual(checkpoint_result.status, "REJECTED")
        self.assertEqual(checkpoint_result.errors[0].code, ErrorCode.INTERNAL_ERROR)

        rollback_result = AdapterPlateCreationService(
            RollbackFailurePort(fail_on_create=True)
        ).execute_plan(make_plan(), confirmed=True)
        self.assertEqual(rollback_result.status, "ROLLBACK_FAILED")
        self.assertFalse(rollback_result.rollback_verified)
        self.assertEqual(rollback_result.errors[-1].code, ErrorCode.ROLLBACK_FAILED)


if __name__ == "__main__":
    unittest.main()
