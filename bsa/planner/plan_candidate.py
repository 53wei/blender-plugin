"""不信任模型输出的候选计划解析与可信 ActionPlan 构造。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable, Mapping
from uuid import uuid4

from ..core.fingerprint import fingerprint_snapshot
from ..core.validator import PlanValidator, relevant_object_ids
from ..domain.actions import Action, ActionPlan, Constraint, action_to_dict
from ..domain.errors import DomainError, ErrorCode
from ..domain.scene import SceneSnapshot
from ..infra.config import MAX_ACTIONS, MAX_DISTANCE


ALLOWED_AI_ACTIONS = frozenset({"place_on", "move", "lock"})
MAX_SUMMARY_CHARS = 500


@dataclass(frozen=True)
class PlanCandidate:
    """模型可以提供的非可信字段；不包含本地安全字段。"""

    schema_version: str
    actions: tuple[Action, ...]
    constraints: tuple[Constraint, ...]
    user_summary: str

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        allowed_object_ids: Iterable[str],
        allowed_action_types: Iterable[str] = ALLOWED_AI_ACTIONS,
    ) -> PlanCandidate:
        """严格解析候选结构，拒绝未知字段、动作和对象。"""

        required = {"schema_version", "actions", "constraints", "user_summary"}
        missing = required - set(payload)
        unknown = set(payload) - required
        if missing or unknown:
            raise DomainError(
                ErrorCode.PLAN_SCHEMA_INVALID,
                "AI candidate contains missing or unknown fields",
                {"missing": sorted(missing), "unknown": sorted(unknown)},
            )
        if payload["schema_version"] != "0.1":
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Unsupported candidate version")
        actions = payload["actions"]
        constraints = payload["constraints"]
        summary = payload["user_summary"]
        if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
            raise DomainError(
                ErrorCode.PLAN_SCHEMA_INVALID,
                "AI candidate must contain a bounded non-empty actions array",
            )
        if not isinstance(constraints, list):
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "constraints must be an array")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY_CHARS:
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "user_summary is invalid")

        allowed_actions = set(allowed_action_types)
        allowed_objects = set(allowed_object_ids)
        action_ids: list[str] = []
        referenced_ids: set[str] = set()
        for action in actions:
            if not isinstance(action, Mapping):
                raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "action must be an object")
            action_type = action.get("type")
            if action_type == "unlock":
                raise DomainError(
                    ErrorCode.OBJECT_LOCKED,
                    "AI cannot unlock objects; use an explicit local unlock instruction first",
                )
            if action_type not in ALLOWED_AI_ACTIONS or action_type not in allowed_actions:
                raise DomainError(
                    ErrorCode.ACTION_NOT_SUPPORTED,
                    "AI action is outside the enabled whitelist",
                    {"type": action_type},
                )
            action_id = action.get("action_id")
            object_id = action.get("object_id")
            if not isinstance(action_id, str) or not action_id:
                raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "action_id must be a string")
            if not isinstance(object_id, str) or not object_id:
                raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "object_id must be a string")
            action_ids.append(action_id)
            referenced_ids.add(object_id)
            if action_type == "place_on":
                target_id = action.get("target_id")
                if not isinstance(target_id, str) or not target_id:
                    raise DomainError(
                        ErrorCode.PLAN_SCHEMA_INVALID, "target_id must be a string"
                    )
                referenced_ids.add(target_id)
        if len(set(action_ids)) != len(action_ids):
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Action IDs must be unique")

        constraint_ids: list[str] = []
        for constraint in constraints:
            if not isinstance(constraint, Mapping):
                raise DomainError(
                    ErrorCode.PLAN_SCHEMA_INVALID, "constraint must be an object"
                )
            constraint_id = constraint.get("constraint_id")
            object_id = constraint.get("object_id")
            if not isinstance(constraint_id, str) or not constraint_id:
                raise DomainError(
                    ErrorCode.PLAN_SCHEMA_INVALID, "constraint_id must be a string"
                )
            if not isinstance(object_id, str) or not object_id:
                raise DomainError(
                    ErrorCode.PLAN_SCHEMA_INVALID,
                    "constraint object_id must be a string",
                )
            constraint_ids.append(constraint_id)
            referenced_ids.add(object_id)
        if len(set(constraint_ids)) != len(constraint_ids):
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Constraint IDs must be unique")
        unknown_objects = referenced_ids - allowed_objects
        if unknown_objects:
            raise DomainError(
                ErrorCode.OBJECT_NOT_FOUND,
                "AI candidate references an object outside the supplied context",
                {"object_ids": sorted(unknown_objects)},
            )

        parsed = ActionPlan.from_dict(
            {
                "schema_version": "0.1",
                "plan_id": "candidate",
                "source": "llm",
                "scene_fingerprint": "",
                "requires_confirmation": True,
                "actions": actions,
                "constraints": constraints,
                "user_summary": summary.strip(),
            }
        )
        return cls(
            schema_version="0.1",
            actions=parsed.actions,
            constraints=parsed.constraints,
            user_summary=summary.strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "actions": [action_to_dict(action) for action in self.actions],
            "constraints": [asdict(constraint) for constraint in self.constraints],
            "user_summary": self.user_summary,
        }


def build_action_plan(
    candidate: PlanCandidate,
    snapshot: SceneSnapshot,
    *,
    plan_id: str | None = None,
) -> ActionPlan:
    """在本地主进程补齐可信字段并执行完整计划校验。"""

    plan = ActionPlan(
        schema_version="0.1",
        plan_id=plan_id or str(uuid4()),
        source="llm",
        scene_fingerprint="",
        requires_confirmation=True,
        actions=candidate.actions,
        constraints=candidate.constraints,
        user_summary=candidate.user_summary,
    )
    plan = replace(
        plan,
        scene_fingerprint=fingerprint_snapshot(snapshot, relevant_object_ids(plan)),
    )
    PlanValidator().validate(plan, snapshot)
    return plan


def candidate_action_schema() -> dict[str, Any]:
    """返回发送给模型的受支持候选协议说明。"""

    return {
        "schema_version": "0.1",
        "allowed_actions": ["place_on", "move", "lock"],
        "allowed_constraints": ["preserve_transform"],
        "regions": ["center", "left", "right", "front", "back"],
        "move_space": "world",
        "action_examples": [
            {
                "action_id": "place-1",
                "type": "place_on",
                "object_id": "OBJECT_ID_FROM_SCENE_CONTEXT",
                "target_id": "ANOTHER_OBJECT_ID_FROM_SCENE_CONTEXT",
                "region": "right",
                "clearance": 0.0,
            },
            {
                "action_id": "move-1",
                "type": "move",
                "object_id": "OBJECT_ID_FROM_SCENE_CONTEXT",
                "delta": [0.5, 0.0, 0.0],
                "space": "world",
            },
            {
                "action_id": "lock-1",
                "type": "lock",
                "object_id": "OBJECT_ID_FROM_SCENE_CONTEXT",
            },
        ],
        "constraint_example": {
            "constraint_id": "preserve-1",
            "type": "preserve_transform",
            "object_id": "OBJECT_ID_FROM_SCENE_CONTEXT",
            "severity": "hard",
        },
        "candidate_fields": [
            "schema_version",
            "actions",
            "constraints",
            "user_summary",
        ],
    }


def candidate_json_schema(
    allowed_object_ids: Iterable[str], allowed_action_types: Iterable[str] = ALLOWED_AI_ACTIONS,
) -> dict[str, Any]:
    """生成受限候选的正式 Schema；不能替代本地语义和状态校验。"""
    object_ids = sorted(set(allowed_object_ids))
    enabled = set(allowed_action_types) & ALLOWED_AI_ACTIONS
    if not object_ids or not enabled:
        raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Candidate schema needs objects and actions")

    def closed_object(properties: dict[str, Any]) -> dict[str, Any]:
        return {"type": "object", "properties": properties,
                "required": list(properties), "additionalProperties": False}

    identifier = {"type": "string", "minLength": 1}
    object_id = {"type": "string", "enum": object_ids}
    actions = []
    for action_type in ("place_on", "move", "lock"):
        if action_type not in enabled:
            continue
        fields = {"action_id": identifier, "type": {"type": "string", "const": action_type},
                  "object_id": object_id}
        if action_type == "place_on":
            fields.update(
                target_id=object_id,
                region={"type": "string", "enum": ["center", "left", "right", "front", "back"]},
                clearance={"type": "number", "minimum": 0, "maximum": MAX_DISTANCE},
            )
        elif action_type == "move":
            fields.update(
                delta={"type": "array", "items": {"type": "number", "minimum": -MAX_DISTANCE,
                                                  "maximum": MAX_DISTANCE},
                       "minItems": 3, "maxItems": 3},
                space={"type": "string", "const": "world"},
            )
        actions.append(closed_object(fields))
    constraint = closed_object({
        "constraint_id": identifier,
        "type": {"type": "string", "const": "preserve_transform"},
        "object_id": object_id, "severity": {"type": "string", "const": "hard"},
    })
    return closed_object({
        "schema_version": {"type": "string", "const": "0.1"},
        "actions": {"type": "array", "items": {"anyOf": actions},
                    "minItems": 1, "maxItems": MAX_ACTIONS},
        "constraints": {"type": "array", "items": constraint},
        "user_summary": {"type": "string", "minLength": 1, "maxLength": MAX_SUMMARY_CHARS},
    })
