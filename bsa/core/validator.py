"""Plan reference, safety, lock, and stale-state validation."""

from __future__ import annotations

import math

from .fingerprint import fingerprint_snapshot
from ..domain.actions import (
    ActionPlan,
    LockAction,
    MoveAction,
    PlaceOnAction,
    RelativePlaceAction,
    UnlockAction,
)
from ..domain.errors import DomainError, ErrorCode
from ..domain.scene import SceneSnapshot
from ..infra.config import MAX_ACTIONS, MAX_DISTANCE


def relevant_object_ids(plan: ActionPlan) -> tuple[str, ...]:
    """Return every object referenced by actions or constraints."""
    result: set[str] = set()
    for action in plan.actions:
        result.add(action.object_id)
        if isinstance(action, (PlaceOnAction, RelativePlaceAction)):
            result.add(action.target_id)
    result.update(constraint.object_id for constraint in plan.constraints)
    return tuple(sorted(result))


def affected_object_ids(plan: ActionPlan) -> tuple[str, ...]:
    """Return objects whose state the plan is authorized to change."""
    return tuple(sorted({action.object_id for action in plan.actions}))


class PlanValidator:
    """Fail-closed validation performed immediately before execution."""

    def validate(self, plan: ActionPlan, snapshot: SceneSnapshot) -> None:
        """Raise a structured error when a plan is unsafe or stale."""
        if plan.schema_version != "0.1" or plan.source not in {
            "local_parser",
            "llm",
            "test",
            "ui",
        }:
            raise DomainError(
                ErrorCode.PLAN_SCHEMA_INVALID, "Plan version or source is unsupported"
            )
        if not plan.plan_id or not plan.actions:
            raise DomainError(
                ErrorCode.PLAN_SCHEMA_INVALID, "A plan needs an ID and at least one action"
            )
        if len(plan.actions) > MAX_ACTIONS:
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Plan has too many actions")
        action_ids = [action.action_id for action in plan.actions]
        if any(not value for value in action_ids) or len(set(action_ids)) != len(action_ids):
            raise DomainError(
                ErrorCode.PLAN_SCHEMA_INVALID, "Action IDs must be non-empty and unique"
            )
        constraint_ids = [constraint.constraint_id for constraint in plan.constraints]
        if len(set(constraint_ids)) != len(constraint_ids):
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Constraint IDs must be unique")

        objects = snapshot.object_map()
        for object_id in relevant_object_ids(plan):
            if object_id not in objects:
                raise DomainError(
                    ErrorCode.OBJECT_NOT_FOUND,
                    "Plan references an object that is not in the current scene",
                    {"object_id": object_id},
                )

        expected = fingerprint_snapshot(snapshot, relevant_object_ids(plan))
        if plan.scene_fingerprint != expected:
            raise DomainError(
                ErrorCode.PLAN_STALE,
                "Scene changed after plan preview; generate a new preview",
                {"expected": plan.scene_fingerprint, "actual": expected},
            )

        relations: dict[tuple[str, str], set[str]] = {}
        locked_state = {object_id: obj.locked for object_id, obj in objects.items()}
        for action in plan.actions:
            obj = objects[action.object_id]
            if plan.source == "llm" and isinstance(action, UnlockAction):
                raise DomainError(
                    ErrorCode.OBJECT_LOCKED,
                    "AI cannot unlock objects; use an explicit local unlock instruction first",
                    {"object_id": obj.object_id},
                )
            writes_transform = isinstance(action, (PlaceOnAction, RelativePlaceAction, MoveAction))
            if writes_transform and locked_state[action.object_id]:
                raise DomainError(
                    ErrorCode.OBJECT_LOCKED,
                    "A locked object cannot be moved",
                    {"object_id": obj.object_id, "action_id": action.action_id},
                )
            if isinstance(action, RelativePlaceAction):
                if not 0.0 <= action.distance <= MAX_DISTANCE:
                    raise DomainError(
                        ErrorCode.PRECONDITION_FAILED,
                        "Relative placement distance is outside the safe range",
                    )
                relations.setdefault((action.object_id, action.target_id), set()).add(
                    action.relation
                )
            if isinstance(action, MoveAction):
                distance = math.sqrt(sum(component * component for component in action.delta))
                if not 0.0 < distance <= MAX_DISTANCE:
                    raise DomainError(
                        ErrorCode.PRECONDITION_FAILED,
                        "Move distance is outside the safe range",
                    )
            if isinstance(action, PlaceOnAction) and not 0.0 <= action.clearance <= MAX_DISTANCE:
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "Surface clearance is outside the safe range",
                )
            if isinstance(action, PlaceOnAction):
                if action.object_id == action.target_id:
                    raise DomainError(
                        ErrorCode.PRECONDITION_FAILED,
                        "An object cannot be placed on itself",
                    )
                if obj.object_type != "MESH" or objects[action.target_id].object_type != "MESH":
                    raise DomainError(
                        ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
                        "M1 place_on only supports mesh objects",
                    )
            if isinstance(action, UnlockAction) and not locked_state[action.object_id]:
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "Object is already unlocked",
                    {"object_id": obj.object_id},
                )
            if isinstance(action, UnlockAction):
                locked_state[action.object_id] = False
            if isinstance(action, LockAction) and locked_state[action.object_id]:
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "Object is already locked",
                    {"object_id": obj.object_id},
                )
            if isinstance(action, LockAction):
                locked_state[action.object_id] = True

        contradictions = ({"left_of", "right_of"}, {"front_of", "back_of"})
        for pair, found in relations.items():
            if any(group <= found for group in contradictions):
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "Plan contains contradictory hard relations",
                    {"object_ids": pair, "relations": sorted(found)},
                )
