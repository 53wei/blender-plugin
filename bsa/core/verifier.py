"""Structured postcondition and unauthorized-change verification."""

from __future__ import annotations

import math

from ..domain.actions import (
    ActionPlan,
    LockAction,
    MoveAction,
    PlaceOnAction,
    PreserveTransformConstraint,
    RelativePlaceAction,
    RotateAction,
    ScaleUniformAction,
    UnlockAction,
)
from ..domain.results import CheckResult, VerificationResult
from ..domain.scene import SceneSnapshot
from ..infra.config import LOCK_TRANSFORM_EPS, POSITION_EPS, SURFACE_GAP_EPS
from .diff import changed_transform_ids, max_matrix_delta


def _place_on_checks(action: PlaceOnAction, after: SceneSnapshot) -> list[CheckResult]:
    objects = after.object_map()
    source = objects[action.object_id]
    target = objects[action.target_id]
    actual_gap = source.bbox_world.min_xyz[2] - target.bbox_world.max_xyz[2]
    checks = [
        CheckResult(
            check_type="place_on",
            object_ids=(action.object_id, action.target_id),
            expected=action.clearance,
            actual=actual_gap,
            tolerance=SURFACE_GAP_EPS,
            passed=abs(actual_gap - action.clearance) <= SURFACE_GAP_EPS,
        )
    ]
    x, y, _z = source.bbox_world.center
    within = (
        target.bbox_world.min_xyz[0] - POSITION_EPS
        <= x
        <= target.bbox_world.max_xyz[0] + POSITION_EPS
        and target.bbox_world.min_xyz[1] - POSITION_EPS
        <= y
        <= target.bbox_world.max_xyz[1] + POSITION_EPS
    )
    checks.append(
        CheckResult(
            check_type="footprint",
            object_ids=(action.object_id, action.target_id),
            expected="source center inside target XY footprint",
            actual=(x, y),
            tolerance=POSITION_EPS,
            passed=within,
        )
    )
    if action.region in {"left", "right", "front", "back"}:
        target_center = target.bbox_world.center
        region_passed = {
            "left": x < target_center[0],
            "right": x > target_center[0],
            "front": y < target_center[1],
            "back": y > target_center[1],
        }[action.region]
        checks.append(
            CheckResult(
                check_type=f"region_{action.region}",
                object_ids=(action.object_id, action.target_id),
                expected=action.region,
                actual=(x, y),
                tolerance=POSITION_EPS,
                passed=region_passed,
            )
        )
    return checks


def _relative_check(action: RelativePlaceAction, after: SceneSnapshot) -> CheckResult:
    objects = after.object_map()
    source = objects[action.object_id].bbox_world
    target = objects[action.target_id].bbox_world
    actual = {
        "right_of": source.min_xyz[0] - target.max_xyz[0],
        "left_of": target.min_xyz[0] - source.max_xyz[0],
        "front_of": target.min_xyz[1] - source.max_xyz[1],
        "back_of": source.min_xyz[1] - target.max_xyz[1],
    }[action.relation]
    return CheckResult(
        check_type=action.relation,
        object_ids=(action.object_id, action.target_id),
        expected=action.distance,
        actual=actual,
        tolerance=POSITION_EPS,
        passed=actual + POSITION_EPS >= action.distance,
    )


class Verifier:
    """Verify postconditions from scene state, never from screenshots."""

    def verify(
        self,
        plan: ActionPlan,
        before: SceneSnapshot,
        after: SceneSnapshot,
        affected_ids: tuple[str, ...],
    ) -> VerificationResult:
        """Return structured checks for all actions and constraints."""
        checks: list[CheckResult] = []
        after_map = after.object_map()
        before_map = before.object_map()
        for action in plan.actions:
            if isinstance(action, PlaceOnAction):
                checks.extend(_place_on_checks(action, after))
            elif isinstance(action, RelativePlaceAction):
                checks.append(_relative_check(action, after))
            elif isinstance(action, MoveAction):
                expected = tuple(
                    value + delta
                    for value, delta in zip(
                        before_map[action.object_id].location_world, action.delta, strict=True
                    )
                )
                actual = after_map[action.object_id].location_world
                delta = max(
                    abs(left - right) for left, right in zip(expected, actual, strict=True)
                )
                checks.append(
                    CheckResult(
                        check_type="move",
                        object_ids=(action.object_id,),
                        expected=expected,
                        actual=actual,
                        tolerance=POSITION_EPS,
                        passed=delta <= POSITION_EPS,
                    )
                )
            elif isinstance(action, RotateAction):
                axis_index = {"x": 0, "y": 1, "z": 2}[action.axis]
                expected = (
                    before_map[action.object_id].rotation_euler[axis_index]
                    + action.angle_radians
                )
                actual = after_map[action.object_id].rotation_euler[axis_index]
                angular_delta = abs(
                    math.atan2(math.sin(actual - expected), math.cos(actual - expected))
                )
                checks.append(
                    CheckResult(
                        check_type=f"rotate_{action.axis}",
                        object_ids=(action.object_id,),
                        expected=expected,
                        actual=actual,
                        tolerance=POSITION_EPS,
                        passed=angular_delta <= POSITION_EPS,
                    )
                )
            elif isinstance(action, ScaleUniformAction):
                expected = tuple(
                    value * action.factor
                    for value in before_map[action.object_id].scale
                )
                actual = after_map[action.object_id].scale
                scale_delta = max(
                    abs(left - right)
                    for left, right in zip(expected, actual, strict=True)
                )
                checks.append(
                    CheckResult(
                        check_type="scale_uniform",
                        object_ids=(action.object_id,),
                        expected=expected,
                        actual=actual,
                        tolerance=POSITION_EPS,
                        passed=scale_delta <= POSITION_EPS,
                    )
                )
            elif isinstance(action, (LockAction, UnlockAction)):
                expected_locked = isinstance(action, LockAction)
                checks.append(
                    CheckResult(
                        check_type=action.type,
                        object_ids=(action.object_id,),
                        expected=expected_locked,
                        actual=after_map[action.object_id].locked,
                        tolerance=None,
                        passed=after_map[action.object_id].locked is expected_locked,
                    )
                )

        for constraint in plan.constraints:
            if isinstance(constraint, PreserveTransformConstraint):
                delta = max_matrix_delta(
                    before_map[constraint.object_id], after_map[constraint.object_id]
                )
                checks.append(
                    CheckResult(
                        check_type="preserve_transform",
                        object_ids=(constraint.object_id,),
                        expected=0.0,
                        actual=delta,
                        tolerance=LOCK_TRANSFORM_EPS,
                        passed=delta <= LOCK_TRANSFORM_EPS,
                    )
                )

        changed = changed_transform_ids(before, after, tolerance=POSITION_EPS)
        affected = set(affected_ids)
        unauthorized = tuple(object_id for object_id in changed if object_id not in affected)
        checks.append(
            CheckResult(
                check_type="unauthorized_changes",
                object_ids=unauthorized,
                expected=[],
                actual=list(unauthorized),
                tolerance=POSITION_EPS,
                passed=not unauthorized,
            )
        )
        passed = all(check.passed for check in checks)
        return VerificationResult(
            passed=passed,
            checks=tuple(checks),
            unauthorized_changes=unauthorized,
            summary="All postconditions passed" if passed else "One or more postconditions failed",
        )
