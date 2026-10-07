"""将明确的中文摆放指令转换为受约束 ActionPlan。"""

from __future__ import annotations

import re
from dataclasses import replace
from uuid import uuid4

from ..core.fingerprint import fingerprint_snapshot
from ..core.validator import relevant_object_ids
from ..domain.actions import (
    ActionPlan,
    LockAction,
    MoveAction,
    PlaceOnAction,
    PreserveTransformConstraint,
    UnlockAction,
)
from ..domain.errors import DomainError, ErrorCode
from ..domain.scene import ObjectState, SceneSnapshot
from ..infra.config import MAX_DISTANCE


_PLACE_PATTERN = re.compile(
    r"^\s*(?:请)?(?:把|将)\s*(?P<source>.+?)\s*"
    r"(?:放到|放在)\s*(?P<target>.+?)\s*(?:的)?\s*"
    r"(?P<region>中央|中间|左侧|右侧|前侧|后侧|上面|表面)"
    r"(?P<tail>.*?)\s*[。！!]?\s*$"
)

_MOVE_PATTERN = re.compile(
    r"^\s*(?:请)?(?:把|将)?\s*(?P<source>.+?)\s*"
    r"(?:向)?(?P<direction>左|右|前|后)(?:移动|移)\s*"
    r"(?P<distance>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>毫米|厘米|米|mm|cm|m)\s*[。！!]?\s*$",
    re.IGNORECASE,
)

_LOCK_PATTERN = re.compile(
    r"^\s*(?:请)?(?P<operation>解除锁定|解锁|锁定)\s*"
    r"(?P<object>.+?)\s*[。！!]?\s*$"
)

_REGIONS = {
    "中央": "center",
    "中间": "center",
    "上面": "center",
    "表面": "center",
    "左侧": "left",
    "右侧": "right",
    "前侧": "front",
    "后侧": "back",
}

_REGION_LABELS = {
    "center": "中央",
    "left": "左侧",
    "right": "右侧",
    "front": "前侧",
    "back": "后侧",
}

_MOVE_DELTAS = {
    "右": (1.0, 0.0, 0.0),
    "左": (-1.0, 0.0, 0.0),
    "前": (0.0, -1.0, 0.0),
    "后": (0.0, 1.0, 0.0),
}

_UNIT_TO_METERS = {
    "米": 1.0,
    "m": 1.0,
    "厘米": 0.01,
    "cm": 0.01,
    "毫米": 0.001,
    "mm": 0.001,
}

_UNIT_LABELS = {
    "米": "米",
    "m": "米",
    "厘米": "厘米",
    "cm": "厘米",
    "毫米": "毫米",
    "mm": "毫米",
}


def _clean_name(value: str) -> str:
    """移除对象名称两端的空白与常见引号。"""

    return value.strip().strip('"\'“”‘’')


def _resolve_object(name: str, snapshot: SceneSnapshot) -> ObjectState:
    """优先精确匹配名称，只在唯一时允许忽略大小写。"""

    exact = [obj for obj in snapshot.objects if obj.name == name]
    if len(exact) == 1:
        return exact[0]
    folded = [obj for obj in snapshot.objects if obj.name.casefold() == name.casefold()]
    if len(folded) == 1:
        return folded[0]
    if len(folded) > 1:
        raise DomainError(
            ErrorCode.PRECONDITION_FAILED,
            "Object name is ambiguous",
            {"name": name, "matches": [obj.name for obj in folded]},
        )
    raise DomainError(
        ErrorCode.OBJECT_NOT_FOUND,
        "Instruction references an object that is not in the scene",
        {"name": name},
    )


def _parse_lock(tail: str, target_name: str) -> bool:
    """只接受明确的锁定或不锁定说法，其他附加要求全部拒绝。"""

    normalized = re.sub(r"[\s，,。！!]", "", tail)
    if not normalized:
        return False
    lock_phrases = {
        "锁定",
        "并锁定",
        "且锁定",
        "锁定目标",
        "并锁定目标",
        "且锁定目标",
        f"锁定{target_name}",
        f"并锁定{target_name}",
        f"且锁定{target_name}",
    }
    no_lock_phrases = {
        "不锁定",
        "不要锁定",
        "不锁定目标",
        f"不锁定{target_name}",
        f"不要锁定{target_name}",
    }
    if normalized in lock_phrases:
        return True
    if normalized in no_lock_phrases:
        return False
    raise DomainError(
        ErrorCode.ACTION_NOT_SUPPORTED,
        "Instruction contains an unsupported extra requirement",
        {"tail": tail.strip()},
    )


class LocalIntentParser:
    """解析明确的单步摆放、移动和锁定指令，不对模糊意图做推测。"""

    @staticmethod
    def _finish_plan(
        snapshot: SceneSnapshot,
        actions: tuple[PlaceOnAction | MoveAction | LockAction | UnlockAction, ...],
        user_summary: str,
        constraints: tuple[PreserveTransformConstraint, ...] = (),
    ) -> ActionPlan:
        """构造统一的可确认计划并绑定相关对象指纹。"""

        plan = ActionPlan(
            schema_version="0.1",
            plan_id=str(uuid4()),
            source="local_parser",
            scene_fingerprint="",
            requires_confirmation=True,
            actions=actions,
            constraints=constraints,
            user_summary=user_summary,
        )
        return replace(
            plan,
            scene_fingerprint=fingerprint_snapshot(
                snapshot, relevant_object_ids(plan)
            ),
        )

    def parse(self, instruction: str, snapshot: SceneSnapshot) -> ActionPlan:
        """返回需要用户确认的计划，或返回结构化错误。"""

        if not instruction.strip() or len(instruction) > 500:
            raise DomainError(
                ErrorCode.ACTION_NOT_SUPPORTED,
                "Instruction is empty or too long",
            )
        place_match = _PLACE_PATTERN.fullmatch(instruction)
        if place_match is not None:
            source_name = _clean_name(place_match.group("source"))
            target_name = _clean_name(place_match.group("target"))
            source = _resolve_object(source_name, snapshot)
            target = _resolve_object(target_name, snapshot)
            if source.object_id == target.object_id:
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "Source and target must be different objects",
                )

            region = _REGIONS[place_match.group("region")]
            lock_target = _parse_lock(place_match.group("tail"), target.name)
            actions: list[PlaceOnAction | LockAction] = [
                PlaceOnAction(
                    action_id="place-1",
                    object_id=source.object_id,
                    target_id=target.object_id,
                    region=region,
                    clearance=0.0,
                )
            ]
            if lock_target:
                actions.append(
                    LockAction(action_id="lock-1", object_id=target.object_id)
                )
            return self._finish_plan(
                snapshot,
                tuple(actions),
                f"将 {source.name} 放到 {target.name} 的{_REGION_LABELS[region]}"
                + (f"，完成后锁定 {target.name}" if lock_target else ""),
                (
                    PreserveTransformConstraint(
                        constraint_id="preserve-1", object_id=target.object_id
                    ),
                ),
            )

        move_match = _MOVE_PATTERN.fullmatch(instruction)
        if move_match is not None:
            source = _resolve_object(
                _clean_name(move_match.group("source")), snapshot
            )
            if source.locked:
                raise DomainError(
                    ErrorCode.OBJECT_LOCKED,
                    "A locked object cannot be moved",
                    {"object_id": source.object_id},
                )
            distance = float(move_match.group("distance"))
            if distance <= 0.0 or snapshot.unit_scale <= 0.0:
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "Move distance and scene unit scale must be positive",
                )
            unit = move_match.group("unit").casefold()
            distance_scene_units = distance * _UNIT_TO_METERS[unit] / snapshot.unit_scale
            if distance_scene_units > MAX_DISTANCE:
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "Move distance is outside the safe range",
                )
            direction = move_match.group("direction")
            direction_vector = _MOVE_DELTAS[direction]
            delta = tuple(
                component * distance_scene_units for component in direction_vector
            )
            return self._finish_plan(
                snapshot,
                (
                    MoveAction(
                        action_id="move-1",
                        object_id=source.object_id,
                        delta=delta,  # type: ignore[arg-type]
                    ),
                ),
                f"将 {source.name} 向{direction}移动 {distance:g} {_UNIT_LABELS[unit]}",
            )

        lock_match = _LOCK_PATTERN.fullmatch(instruction)
        if lock_match is not None:
            obj = _resolve_object(
                _clean_name(lock_match.group("object")), snapshot
            )
            operation = lock_match.group("operation")
            should_lock = operation == "锁定"
            if obj.locked is should_lock:
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "Object already has the requested lock state",
                    {"object_id": obj.object_id, "locked": obj.locked},
                )
            action = (
                LockAction(action_id="lock-1", object_id=obj.object_id)
                if should_lock
                else UnlockAction(action_id="unlock-1", object_id=obj.object_id)
            )
            return self._finish_plan(
                snapshot,
                (action,),
                f"{'锁定' if should_lock else '解除锁定'} {obj.name}",
            )

        raise DomainError(
            ErrorCode.ACTION_NOT_SUPPORTED,
            "Instruction is outside the explicit local grammar",
            {
                "examples": [
                    "把 Lamp 放到 Desk 右侧",
                    "Lamp 向右移动 20 厘米",
                    "锁定 Desk",
                ]
            },
        )
