"""All-or-nothing scene-plan execution."""

from __future__ import annotations

from .ports import ScenePort
from ..core.spatial import place_on_location, relative_place_location
from ..core.validator import PlanValidator, affected_object_ids
from ..core.verifier import Verifier
from ..domain.actions import (
    ActionPlan,
    LockAction,
    MoveAction,
    PlaceOnAction,
    RelativePlaceAction,
    UnlockAction,
)
from ..domain.errors import DomainError, ErrorCode
from ..domain.results import ExecutionResult


class SceneEditingService:
    """Coordinate validation, checkpoint, execution, verification, and rollback."""

    def __init__(
        self,
        scene: ScenePort,
        *,
        validator: PlanValidator | None = None,
        verifier: Verifier | None = None,
    ) -> None:
        self._scene = scene
        self._validator = validator or PlanValidator()
        self._verifier = verifier or Verifier()

    def execute_plan(self, plan: ActionPlan, *, confirmed: bool = False) -> ExecutionResult:
        """Execute a complete plan or leave the scene at its pre-plan state."""
        if plan.requires_confirmation and not confirmed:
            error = DomainError(
                ErrorCode.PRECONDITION_FAILED,
                "Plan requires explicit user confirmation before execution",
            )
            return ExecutionResult(
                status="REJECTED", plan_id=plan.plan_id, verification=None, errors=(error,)
            )
        before = self._scene.read_snapshot()
        try:
            self._validator.validate(plan, before)
        except DomainError as error:
            return ExecutionResult(status="REJECTED", plan_id=plan.plan_id, verification=None, errors=(error,))

        affected = affected_object_ids(plan)
        checkpoint_ids = tuple(sorted(obj.object_id for obj in before.objects))
        checkpoint = self._scene.capture_checkpoint(checkpoint_ids)
        try:
            for action in plan.actions:
                current = self._scene.read_snapshot().object_map()
                if isinstance(action, PlaceOnAction):
                    location = place_on_location(
                        current[action.object_id],
                        current[action.target_id],
                        region=action.region,
                        clearance=action.clearance,
                    )
                    self._scene.apply_location(action.object_id, location)
                elif isinstance(action, RelativePlaceAction):
                    location = relative_place_location(
                        current[action.object_id],
                        current[action.target_id],
                        relation=action.relation,
                        distance=action.distance,
                    )
                    self._scene.apply_location(action.object_id, location)
                elif isinstance(action, MoveAction):
                    source = current[action.object_id]
                    location = tuple(
                        value + delta
                        for value, delta in zip(
                            source.location_world, action.delta, strict=True
                        )
                    )
                    self._scene.apply_location(action.object_id, location)  # type: ignore[arg-type]
                elif isinstance(action, LockAction):
                    self._scene.set_locked(action.object_id, True)
                elif isinstance(action, UnlockAction):
                    self._scene.set_locked(action.object_id, False)

            after = self._scene.read_snapshot()
            verification = self._verifier.verify(plan, before, after, affected)
            if verification.passed:
                return ExecutionResult(
                    status="COMMITTED", plan_id=plan.plan_id, verification=verification
                )
            error_code = (
                ErrorCode.UNAUTHORIZED_CHANGE
                if verification.unauthorized_changes
                else ErrorCode.POSTCONDITION_FAILED
            )
            raise DomainError(error_code, verification.summary)
        except DomainError as error:
            rollback_verified = self._scene.restore_checkpoint(checkpoint)
            if not rollback_verified:
                rollback_error = DomainError(
                    ErrorCode.ROLLBACK_FAILED, "Checkpoint restore could not be verified"
                )
                return ExecutionResult(
                    status="ROLLBACK_FAILED",
                    plan_id=plan.plan_id,
                    verification=None,
                    errors=(error, rollback_error),
                    rollback_verified=False,
                )
            return ExecutionResult(
                status="ROLLED_BACK",
                plan_id=plan.plan_id,
                verification=None,
                errors=(error,),
                rollback_verified=True,
            )
        except Exception as unexpected:
            rollback_verified = self._scene.restore_checkpoint(checkpoint)
            error = DomainError(
                ErrorCode.INTERNAL_ERROR,
                "Unexpected executor failure",
                {"exception_type": type(unexpected).__name__},
            )
            status = "ROLLED_BACK" if rollback_verified else "ROLLBACK_FAILED"
            return ExecutionResult(
                status=status,
                plan_id=plan.plan_id,
                verification=None,
                errors=(error,),
                rollback_verified=rollback_verified,
            )
