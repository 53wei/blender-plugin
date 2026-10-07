"""Strict Action Protocol v0.1 dataclasses and JSON conversion."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, TypeAlias

from .errors import DomainError, ErrorCode


def _expect_fields(
    payload: Mapping[str, Any], *, required: set[str], optional: set[str] | None = None
) -> None:
    optional = optional or set()
    keys = set(payload)
    missing = required - keys
    unknown = keys - required - optional
    if missing or unknown:
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "Action plan contains missing or unknown fields",
            {"missing": sorted(missing), "unknown": sorted(unknown)},
        )


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID, f"{field_name} must be a finite number"
        )
    result = float(value)
    if not math.isfinite(result):
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID, f"{field_name} must be a finite number"
        )
    return result


@dataclass(frozen=True)
class PlaceOnAction:
    action_id: str
    object_id: str
    target_id: str
    region: str = "center"
    clearance: float = 0.0
    type: str = field(default="place_on", init=False)


@dataclass(frozen=True)
class RelativePlaceAction:
    action_id: str
    object_id: str
    target_id: str
    relation: str
    distance: float
    frame: str = "world"
    type: str = field(default="relative_place", init=False)


@dataclass(frozen=True)
class MoveAction:
    action_id: str
    object_id: str
    delta: tuple[float, float, float]
    space: str = "world"
    type: str = field(default="move", init=False)


@dataclass(frozen=True)
class LockAction:
    action_id: str
    object_id: str
    type: str = field(default="lock", init=False)


@dataclass(frozen=True)
class UnlockAction:
    action_id: str
    object_id: str
    type: str = field(default="unlock", init=False)


Action: TypeAlias = PlaceOnAction | RelativePlaceAction | MoveAction | LockAction | UnlockAction


def action_to_dict(action: Action) -> dict[str, Any]:
    """输出 JSON 协议数据，内部不可变向量转换为 JSON 数组。"""
    payload = asdict(action)
    if isinstance(action, MoveAction):
        payload["delta"] = list(action.delta)
    return payload


@dataclass(frozen=True)
class PreserveTransformConstraint:
    constraint_id: str
    object_id: str
    severity: str = field(default="hard", init=False)
    type: str = field(default="preserve_transform", init=False)


Constraint: TypeAlias = PreserveTransformConstraint


def _parse_action(payload: Mapping[str, Any]) -> Action:
    action_type = payload.get("type")
    if action_type == "place_on":
        _expect_fields(
            payload,
            required={"action_id", "type", "object_id", "target_id", "region", "clearance"},
        )
        region = payload["region"]
        if region not in {"center", "left", "right", "front", "back"}:
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Unsupported place_on region")
        return PlaceOnAction(
            action_id=str(payload["action_id"]),
            object_id=str(payload["object_id"]),
            target_id=str(payload["target_id"]),
            region=str(region),
            clearance=_finite_number(payload["clearance"], "clearance"),
        )
    if action_type == "relative_place":
        _expect_fields(
            payload,
            required={
                "action_id",
                "type",
                "object_id",
                "target_id",
                "relation",
                "distance",
                "frame",
            },
        )
        relation = payload["relation"]
        if relation not in {"left_of", "right_of", "front_of", "back_of"}:
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Unsupported relative relation")
        if payload["frame"] != "world":
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "M1 only supports world frame")
        return RelativePlaceAction(
            action_id=str(payload["action_id"]),
            object_id=str(payload["object_id"]),
            target_id=str(payload["target_id"]),
            relation=str(relation),
            distance=_finite_number(payload["distance"], "distance"),
        )
    if action_type == "move":
        _expect_fields(
            payload, required={"action_id", "type", "object_id", "delta", "space"}
        )
        delta = payload["delta"]
        if not isinstance(delta, list) or len(delta) != 3:
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "move.delta must have three numbers")
        if payload["space"] != "world":
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "M1 only supports world-space move")
        parsed_delta = tuple(_finite_number(value, "delta") for value in delta)
        return MoveAction(
            action_id=str(payload["action_id"]),
            object_id=str(payload["object_id"]),
            delta=parsed_delta,  # type: ignore[arg-type]
        )
    if action_type in {"lock", "unlock"}:
        _expect_fields(payload, required={"action_id", "type", "object_id"})
        action_class = LockAction if action_type == "lock" else UnlockAction
        return action_class(
            action_id=str(payload["action_id"]), object_id=str(payload["object_id"])
        )
    raise DomainError(
        ErrorCode.ACTION_NOT_SUPPORTED,
        "Action type is not in the M1 whitelist",
        {"type": action_type},
    )


def _parse_constraint(payload: Mapping[str, Any]) -> Constraint:
    _expect_fields(
        payload, required={"constraint_id", "type", "object_id", "severity"}
    )
    if payload["type"] != "preserve_transform" or payload["severity"] != "hard":
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "M1 only supports hard preserve_transform constraints",
        )
    return PreserveTransformConstraint(
        constraint_id=str(payload["constraint_id"]), object_id=str(payload["object_id"])
    )


@dataclass(frozen=True)
class ActionPlan:
    """Validated structural representation of an Action Protocol v0.1 plan."""

    schema_version: str
    plan_id: str
    source: str
    scene_fingerprint: str
    requires_confirmation: bool
    actions: tuple[Action, ...]
    constraints: tuple[Constraint, ...]
    user_summary: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ActionPlan":
        """Parse a strict, fail-closed plan."""
        _expect_fields(
            payload,
            required={
                "schema_version",
                "plan_id",
                "source",
                "scene_fingerprint",
                "requires_confirmation",
                "actions",
                "constraints",
                "user_summary",
            },
        )
        if payload["schema_version"] != "0.1":
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Unsupported schema version")
        if payload["source"] not in {"local_parser", "llm", "test", "ui"}:
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Unsupported plan source")
        if not isinstance(payload["requires_confirmation"], bool):
            raise DomainError(
                ErrorCode.PLAN_SCHEMA_INVALID, "requires_confirmation must be boolean"
            )
        if not isinstance(payload["actions"], list) or not isinstance(
            payload["constraints"], list
        ):
            raise DomainError(
                ErrorCode.PLAN_SCHEMA_INVALID, "actions and constraints must be arrays"
            )
        return cls(
            schema_version="0.1",
            plan_id=str(payload["plan_id"]),
            source=str(payload["source"]),
            scene_fingerprint=str(payload["scene_fingerprint"]),
            requires_confirmation=payload["requires_confirmation"],
            actions=tuple(_parse_action(item) for item in payload["actions"]),
            constraints=tuple(_parse_constraint(item) for item in payload["constraints"]),
            user_summary=str(payload["user_summary"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the public JSON protocol shape."""
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "source": self.source,
            "scene_fingerprint": self.scene_fingerprint,
            "requires_confirmation": self.requires_confirmation,
            "actions": [action_to_dict(action) for action in self.actions],
            "constraints": [asdict(constraint) for constraint in self.constraints],
            "user_summary": self.user_summary,
        }
