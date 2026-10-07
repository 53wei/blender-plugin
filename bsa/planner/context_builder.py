"""为模型规划构建可审查、可限制的最小场景上下文。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..domain.scene import ObjectState, SceneSnapshot


MAX_CONTEXT_OBJECTS = 20
MAX_INSTRUCTION_CHARS = 500


@dataclass(frozen=True)
class BuiltPlannerContext:
    """一次规划请求的公开对象摘要和用户可见预览。"""

    payload: dict[str, Any]
    object_ids: tuple[str, ...]
    omitted_object_count: int
    preview_text: str


class ContextBuilder:
    """优先选择指令明确提到的对象，否则使用有上限的可见对象集合。"""

    def build(self, instruction: str, snapshot: SceneSnapshot) -> BuiltPlannerContext:
        normalized_instruction = instruction.strip()
        if not normalized_instruction or len(normalized_instruction) > MAX_INSTRUCTION_CHARS:
            raise ValueError("Instruction must contain 1 to 500 characters")

        visible = tuple(
            sorted(
                (obj for obj in snapshot.objects if obj.visible),
                key=lambda item: item.object_id,
            )
        )
        folded_instruction = normalized_instruction.casefold()
        matched = tuple(
            obj
            for obj in visible
            if obj.name.strip() and _name_is_mentioned(obj.name, folded_instruction)
        )
        candidates = matched or visible
        selected = candidates[:MAX_CONTEXT_OBJECTS]
        omitted = max(0, len(candidates) - len(selected))
        summaries = [_object_summary(obj) for obj in selected]
        public_unit_scale = round(float(snapshot.unit_scale), 9)
        payload = {
            "context_version": "0.1",
            "unit_scale": public_unit_scale,
            "objects": summaries,
        }
        preview_lines = [
            "本轮将发送以下数据：",
            f"当前指令：{json.dumps(normalized_instruction, ensure_ascii=False)}",
            f"场景单位比例：{public_unit_scale}",
            f"{len(selected)} 个对象摘要：",
        ]
        preview_lines.extend(_preview_object(summary) for summary in summaries)
        if omitted:
            preview_lines.append(f"另有 {omitted} 个候选对象因 20 个上限未发送。")
        preview_lines.append(
            "不发送网格、材质、纹理、文件、截图、对象矩阵或场景历史。"
        )
        preview = "\n".join(preview_lines)
        return BuiltPlannerContext(
            payload=payload,
            object_ids=tuple(obj.object_id for obj in selected),
            omitted_object_count=omitted,
            preview_text=preview,
        )


def _object_summary(obj: ObjectState) -> dict[str, Any]:
    return {
        "object_id": obj.object_id,
        "name": obj.name,
        "type": obj.object_type,
        "location": _public_vector(obj.location_world),
        "dimensions": _public_vector(obj.dimensions_world),
        "locked": obj.locked,
    }


def _name_is_mentioned(name: str, folded_instruction: str) -> bool:
    """英文数字名称按完整词匹配；中文名称保留自然的连续文本匹配。"""

    folded_name = name.strip().casefold()
    if not folded_name:
        return False
    if all(ord(character) < 128 for character in folded_name):
        pattern = rf"(?<![a-z0-9_]){re.escape(folded_name)}(?![a-z0-9_])"
        return re.search(pattern, folded_instruction) is not None
    return folded_name in folded_instruction


def _preview_object(summary: dict[str, Any]) -> str:
    locked = "是" if summary["locked"] else "否"
    return (
        f"- {summary['name']} | ID={summary['object_id']} | 类型={summary['type']} | "
        f"位置={summary['location']} | 尺寸={summary['dimensions']} | 锁定={locked}"
    )


def _public_vector(values: tuple[float, float, float]) -> list[float]:
    """抑制 Blender 浮点噪声，并让发送值与用户预览完全一致。"""

    return [round(float(value), 6) for value in values]
