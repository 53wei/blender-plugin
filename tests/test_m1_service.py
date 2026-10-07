"""The eight required M1 deterministic-core behaviors."""

from __future__ import annotations

import unittest
from dataclasses import replace

from bsa.application.service import SceneEditingService
from bsa.core.fingerprint import fingerprint_snapshot
from bsa.core.validator import relevant_object_ids
from bsa.domain.actions import ActionPlan, LockAction, MoveAction, PlaceOnAction
from bsa.domain.errors import ErrorCode
from bsa.domain.results import CheckResult, VerificationResult
from bsa.domain.scene import SceneSnapshot
from tests.support import make_place_plan, make_scene


def with_current_fingerprint(plan: ActionPlan, snapshot: SceneSnapshot) -> ActionPlan:
    return replace(
        plan, scene_fingerprint=fingerprint_snapshot(snapshot, relevant_object_ids(plan))
    )


class AlwaysFailVerifier:
    def verify(self, plan, before, after, affected_ids):
        return VerificationResult(
            passed=False,
            checks=(
                CheckResult(
                    check_type="forced_failure",
                    object_ids=("lamp-id",),
                    expected=True,
                    actual=False,
                    tolerance=None,
                    passed=False,
                ),
            ),
            unauthorized_changes=(),
            summary="Forced postcondition failure",
        )


class M1ServiceTests(unittest.TestCase):
    def test_preview_that_requires_confirmation_cannot_execute_silently(self) -> None:
        scene = make_scene()
        plan = replace(make_place_plan(scene), requires_confirmation=True)
        before = scene.read_snapshot().object_map()
        result = SceneEditingService(scene).execute_plan(plan)
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.PRECONDITION_FAILED)
        self.assertEqual(before, scene.read_snapshot().object_map())

    def test_01_place_on_desk_passes(self) -> None:
        scene = make_scene()
        result = SceneEditingService(scene).execute_plan(make_place_plan(scene, region="center"))
        self.assertEqual(result.status, "COMMITTED")
        self.assertTrue(result.verification and result.verification.passed)

    def test_02_place_on_right_passes(self) -> None:
        scene = make_scene()
        result = SceneEditingService(scene).execute_plan(make_place_plan(scene, region="right"))
        self.assertEqual(result.status, "COMMITTED")
        checks = {check.check_type: check for check in result.verification.checks}  # type: ignore[union-attr]
        self.assertTrue(checks["place_on"].passed)
        self.assertTrue(checks["region_right"].passed)

    def test_03_locked_desk_rejects_move_without_changing_state(self) -> None:
        scene = make_scene()
        snapshot = scene.read_snapshot()
        lock_plan = ActionPlan(
            schema_version="0.1",
            plan_id="lock-desk",
            source="test",
            scene_fingerprint="",
            requires_confirmation=False,
            actions=(LockAction(action_id="lock-1", object_id="desk-id"),),
            constraints=(),
            user_summary="Lock Desk",
        )
        lock_plan = with_current_fingerprint(lock_plan, snapshot)
        self.assertEqual(SceneEditingService(scene).execute_plan(lock_plan).status, "COMMITTED")
        locked_snapshot = scene.read_snapshot()
        move_plan = ActionPlan(
            schema_version="0.1",
            plan_id="move-locked-desk",
            source="test",
            scene_fingerprint="",
            requires_confirmation=False,
            actions=(
                MoveAction(action_id="move-1", object_id="desk-id", delta=(1.0, 0.0, 0.0)),
            ),
            constraints=(),
            user_summary="Move Desk",
        )
        move_plan = with_current_fingerprint(move_plan, locked_snapshot)
        result = SceneEditingService(scene).execute_plan(move_plan)
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.OBJECT_LOCKED)
        self.assertEqual(
            locked_snapshot.object_map()["desk-id"].matrix_world,
            scene.read_snapshot().object_map()["desk-id"].matrix_world,
        )

    def test_04_moving_lamp_does_not_change_desk_fingerprint(self) -> None:
        scene = make_scene()
        before = scene.read_snapshot()
        desk_before = fingerprint_snapshot(before, ("desk-id",))
        plan = ActionPlan(
            schema_version="0.1",
            plan_id="move-lamp",
            source="test",
            scene_fingerprint="",
            requires_confirmation=False,
            actions=(
                MoveAction(action_id="move-1", object_id="lamp-id", delta=(0.25, 0.0, 0.0)),
            ),
            constraints=(),
            user_summary="Move Lamp",
        )
        plan = with_current_fingerprint(plan, before)
        self.assertEqual(SceneEditingService(scene).execute_plan(plan).status, "COMMITTED")
        self.assertEqual(desk_before, fingerprint_snapshot(scene.read_snapshot(), ("desk-id",)))

    def test_05_postcondition_failure_rolls_back_exactly(self) -> None:
        scene = make_scene()
        before = scene.read_snapshot().object_map()
        result = SceneEditingService(scene, verifier=AlwaysFailVerifier()).execute_plan(
            make_place_plan(scene)
        )
        self.assertEqual(result.status, "ROLLED_BACK")
        self.assertTrue(result.rollback_verified)
        self.assertEqual(before, scene.read_snapshot().object_map())

    def test_06_stale_preview_is_rejected(self) -> None:
        scene = make_scene()
        plan = make_place_plan(scene)
        lamp_before = scene.read_snapshot().object_map()["lamp-id"]
        scene.apply_location("desk-id", (0.2, 0.0, 0.5))
        result = SceneEditingService(scene).execute_plan(plan)
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.PLAN_STALE)
        self.assertEqual(lamp_before, scene.read_snapshot().object_map()["lamp-id"])

    def test_07_missing_target_does_not_modify_scene(self) -> None:
        scene = make_scene()
        before = scene.read_snapshot().object_map()
        plan = ActionPlan(
            schema_version="0.1",
            plan_id="missing-target",
            source="test",
            scene_fingerprint="sha256:unused",
            requires_confirmation=False,
            actions=(
                PlaceOnAction(
                    action_id="place-1",
                    object_id="lamp-id",
                    target_id="missing-id",
                    region="right",
                    clearance=0.0,
                ),
            ),
            constraints=(),
            user_summary="Invalid target",
        )
        result = SceneEditingService(scene).execute_plan(plan)
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.errors[0].code, ErrorCode.OBJECT_NOT_FOUND)
        self.assertEqual(before, scene.read_snapshot().object_map())

    def test_08_twenty_repeated_runs_are_deterministic(self) -> None:
        locations = []
        for index in range(20):
            scene = make_scene()
            result = SceneEditingService(scene).execute_plan(
                make_place_plan(scene, plan_id=f"repeat-{index}")
            )
            self.assertEqual(result.status, "COMMITTED")
            locations.append(scene.read_snapshot().object_map()["lamp-id"].location_world)
        self.assertEqual(len(set(locations)), 1)


if __name__ == "__main__":
    unittest.main()
