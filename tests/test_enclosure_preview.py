"""参数化外壳 P1 装配预览与创建事务。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from bsa.application.enclosure_service import EnclosurePreviewService
from bsa.application.memory_enclosure import MemoryEnclosurePreviewPort
from bsa.core.enclosure import design_enclosure
from bsa.core.enclosure_preview import build_enclosure_preview_parts
from bsa.domain.enclosure_preview import EnclosurePreviewPlan
from bsa.domain.errors import ErrorCode
from tests.test_enclosure_design import make_board, make_parameters


def make_plan(*, plan_id: str = "preview-001") -> EnclosurePreviewPlan:
    return EnclosurePreviewPlan(
        schema_version="0.1",
        plan_id=plan_id,
        source="test",
        requires_confirmation=True,
        enclosure_id="demo-enclosure",
        design=design_enclosure(make_board(), make_parameters()),
        user_summary="创建电路板外壳装配预览",
    )


class CheckpointFailurePort(MemoryEnclosurePreviewPort):
    def capture_creation_checkpoint(self, transaction_id: str):
        del transaction_id
        raise RuntimeError("injected checkpoint failure")


class RollbackFailurePort(MemoryEnclosurePreviewPort):
    def restore_creation_checkpoint(self, checkpoint, transaction_id: str) -> bool:
        del checkpoint, transaction_id
        raise RuntimeError("injected rollback failure")


class EnclosurePreviewPartTests(unittest.TestCase):
    def test_preview_parts_have_exact_sizes_positions_and_roles(self) -> None:
        parts = build_enclosure_preview_parts(make_plan().design)
        indexed = {part.part_id: part for part in parts}

        self.assertEqual(len(parts), 12)
        self.assertEqual(indexed["base_floor"].dimensions_mm, (76.0, 56.0, 2.0))
        self.assertEqual(indexed["base_floor"].center_mm, (38.0, 28.0, 1.0))
        self.assertEqual(indexed["wall_front"].dimensions_mm, (72.0, 2.0, 19.0))
        self.assertEqual(indexed["lid"].center_mm, (38.0, 28.0, 22.0))
        self.assertEqual(indexed["lid"].display_mode, "wire")
        self.assertEqual(indexed["board_proxy"].dimensions_mm, (70.0, 50.0, 12.0))
        self.assertEqual(indexed["boss_001"].shape, "cylinder")
        self.assertEqual(indexed["boss_001"].dimensions_mm, (6.0, 6.0, 4.0))
        self.assertEqual(indexed["port_usb"].display_mode, "wire")
        self.assertEqual(indexed["port_usb"].dimensions_mm, (13.0, 2.0, 7.0))

    def test_part_generation_is_deterministic_and_serializable(self) -> None:
        first = build_enclosure_preview_parts(make_plan().design)
        second = build_enclosure_preview_parts(make_plan().design)
        self.assertEqual(first, second)
        self.assertEqual(
            [part.to_dict() for part in first],
            [part.to_dict() for part in second],
        )


class EnclosurePreviewServiceTests(unittest.TestCase):
    def test_plan_requires_explicit_confirmation_before_creation(self) -> None:
        port = MemoryEnclosurePreviewPort(existing_objects={"desk": (1.0, 2.0, 3.0)})
        before = port.scene_state()

        result = EnclosurePreviewService(port).execute_plan(make_plan())

        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.PRECONDITION_FAILED)
        self.assertEqual(port.scene_state(), before)

    def test_confirmed_plan_creates_and_verifies_complete_preview(self) -> None:
        port = MemoryEnclosurePreviewPort(existing_objects={"desk": (1.0, 2.0, 3.0)})

        result = EnclosurePreviewService(port).execute_plan(make_plan(), confirmed=True)

        self.assertEqual(result.status, "COMMITTED")
        self.assertTrue(result.verification and result.verification.passed)
        self.assertEqual(len(port.created_parts("preview-001")), 12)
        self.assertEqual(port.existing_objects, {"desk": (1.0, 2.0, 3.0)})

    def test_partial_creation_failure_removes_every_new_part(self) -> None:
        port = MemoryEnclosurePreviewPort(
            existing_objects={"desk": (1.0, 2.0, 3.0)}, fail_after_parts=4
        )
        before = port.scene_state()

        result = EnclosurePreviewService(port).execute_plan(make_plan(), confirmed=True)

        self.assertEqual(result.status, "ROLLED_BACK")
        self.assertTrue(result.rollback_verified)
        self.assertEqual(result.errors[0].code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(port.scene_state(), before)

    def test_postcondition_mismatch_rolls_back_instead_of_weakening_check(self) -> None:
        port = MemoryEnclosurePreviewPort(tamper_part_id="lid")

        result = EnclosurePreviewService(port).execute_plan(make_plan(), confirmed=True)

        self.assertEqual(result.status, "ROLLED_BACK")
        self.assertEqual(result.errors[0].code, ErrorCode.POSTCONDITION_FAILED)
        self.assertEqual(port.created_parts("preview-001"), ())

    def test_existing_enclosure_id_is_rejected_without_mutation(self) -> None:
        port = MemoryEnclosurePreviewPort()
        service = EnclosurePreviewService(port)
        self.assertEqual(service.execute_plan(make_plan(), confirmed=True).status, "COMMITTED")
        before = port.scene_state()

        duplicate = replace(make_plan(plan_id="preview-002"), enclosure_id="demo-enclosure")
        result = service.execute_plan(duplicate, confirmed=True)

        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.PRECONDITION_FAILED)
        self.assertEqual(port.scene_state(), before)

    def test_invalid_plan_schema_is_rejected_before_checkpoint(self) -> None:
        port = MemoryEnclosurePreviewPort()

        result = EnclosurePreviewService(port).execute_plan(
            replace(make_plan(), schema_version="9.9"), confirmed=True
        )

        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.PLAN_SCHEMA_INVALID)
        self.assertEqual(port.checkpoint_count, 0)

    def test_creation_plan_cannot_disable_confirmation(self) -> None:
        port = MemoryEnclosurePreviewPort()

        result = EnclosurePreviewService(port).execute_plan(
            replace(make_plan(), requires_confirmation=False), confirmed=True
        )

        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.PLAN_SCHEMA_INVALID)
        self.assertEqual(port.checkpoint_count, 0)

    def test_handcrafted_invalid_design_is_rejected_before_checkpoint(self) -> None:
        port = MemoryEnclosurePreviewPort()
        invalid_design = replace(make_plan().design, boss_height_mm=-1.0)

        result = EnclosurePreviewService(port).execute_plan(
            replace(make_plan(), design=invalid_design), confirmed=True
        )

        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.PRINT_SPEC_INVALID)
        self.assertEqual(port.checkpoint_count, 0)

    def test_missing_typed_design_is_rejected_without_executor_crash(self) -> None:
        port = MemoryEnclosurePreviewPort()
        invalid_plan = replace(make_plan(), design=None)  # type: ignore[arg-type]

        result = EnclosurePreviewService(port).execute_plan(
            invalid_plan, confirmed=True
        )

        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.PLAN_SCHEMA_INVALID)
        self.assertEqual(port.checkpoint_count, 0)

    def test_checkpoint_failure_is_reported_without_scene_mutation(self) -> None:
        port = CheckpointFailurePort(existing_objects={"desk": (1.0, 2.0, 3.0)})
        before = port.scene_state()

        result = EnclosurePreviewService(port).execute_plan(
            make_plan(), confirmed=True
        )

        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(port.scene_state(), before)

    def test_rollback_exception_becomes_explicit_rollback_failure(self) -> None:
        port = RollbackFailurePort(fail_after_parts=1)

        result = EnclosurePreviewService(port).execute_plan(
            make_plan(), confirmed=True
        )

        self.assertEqual(result.status, "ROLLBACK_FAILED")
        self.assertFalse(result.rollback_verified)
        self.assertEqual(result.errors[-1].code, ErrorCode.ROLLBACK_FAILED)


if __name__ == "__main__":
    unittest.main()
