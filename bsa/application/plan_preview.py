"""根据可信动作结构生成确认前的中文说明，不依赖模型摘要。"""

from __future__ import annotations

from ..domain.actions import (
    ActionPlan,
    LockAction,
    MoveAction,
    PlaceOnAction,
    PreserveTransformConstraint,
    RelativePlaceAction,
    UnlockAction,
)
from ..domain.scene import SceneSnapshot


def _vector(values: tuple[float, ...]) -> str:
    return "[" + ", ".join(f"{value:.6g}" for value in values) + "]"


def describe_plan(plan: ActionPlan, snapshot: SceneSnapshot) -> str:
    """展示实际动作、对象与约束；模型文本只附在清单之后。"""

    objects = snapshot.object_map()
    names = {object_id: obj.name for object_id, obj in objects.items()}
    regions = {"center": "中央", "left": "左侧", "right": "右侧", "front": "前侧", "back": "后侧"}
    lines = ["实际执行动作（按顺序）："]
    for index, action in enumerate(plan.actions, 1):
        name = names.get(action.object_id, action.object_id)
        if isinstance(action, PlaceOnAction):
            target = names.get(action.target_id, action.target_id)
            detail = (
                f"将 {name} 放到 {target} 的{regions[action.region]}；"
                f"表面间隙 {action.clearance * snapshot.unit_scale:.6g} 米"
            )
        elif isinstance(action, MoveAction):
            meters = tuple(value * snapshot.unit_scale for value in action.delta)
            detail = (
                f"移动 {name}；世界坐标位移 {_vector(action.delta)} 场景单位"
                f"（{_vector(meters)} 米）"
            )
        elif isinstance(action, LockAction):
            detail = f"锁定 {name}"
        elif isinstance(action, UnlockAction):
            detail = f"解除锁定 {name}"
        elif isinstance(action, RelativePlaceAction):
            detail = (
                f"相对摆放 {name} → {names.get(action.target_id, action.target_id)}："
                f"{action.relation}，间距 {action.distance * snapshot.unit_scale:.6g} 米"
            )
        else:
            raise ValueError("无法展示未知动作")
        lines.append(f"{index}. {detail}")
    if plan.constraints:
        lines.append("保护约束：")
        for constraint in plan.constraints:
            if isinstance(constraint, PreserveTransformConstraint):
                lines.append(
                    f"保持 {names.get(constraint.object_id, constraint.object_id)} 的变换不动"
                )
    referenced = {action.object_id for action in plan.actions}
    locked_names = [names[object_id] for object_id in sorted(referenced)
                    if object_id in objects and objects[object_id].locked]
    if locked_names:
        lines.append("当前锁定：" + "、".join(locked_names))
    if plan.source == "llm":
        lines.append("模型建议（实际操作以上述清单为准）：" + plan.user_summary)
    return "\n".join(lines)
