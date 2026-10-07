"""不依赖 Blender 的助手交互状态机。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssistantStatus(str, Enum):
    """用户可以在界面中看到的助手状态。"""

    IDLE = "IDLE"
    AI_REVIEW = "AI_REVIEW"
    PLANNING = "PLANNING"
    PLAN_READY = "PLAN_READY"
    WORKING = "WORKING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class AssistantEvent(str, Enum):
    """由界面操作或执行结果触发的状态事件。"""

    PREVIEW_READY = "PREVIEW_READY"
    AI_REVIEW_READY = "AI_REVIEW_READY"
    AI_PLANNING_STARTED = "AI_PLANNING_STARTED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_SUCCEEDED = "EXECUTION_SUCCEEDED"
    FAILED = "FAILED"
    CLEARED = "CLEARED"


@dataclass(frozen=True)
class AssistantPresentation:
    """状态对应的中文展示内容与强调色。"""

    label: str
    detail: str
    icon: str
    color: tuple[float, float, float]


_TRANSITIONS = {
    (AssistantStatus.IDLE, AssistantEvent.AI_REVIEW_READY): AssistantStatus.AI_REVIEW,
    (AssistantStatus.SUCCESS, AssistantEvent.AI_REVIEW_READY): AssistantStatus.AI_REVIEW,
    (AssistantStatus.ERROR, AssistantEvent.AI_REVIEW_READY): AssistantStatus.AI_REVIEW,
    (
        AssistantStatus.AI_REVIEW,
        AssistantEvent.AI_PLANNING_STARTED,
    ): AssistantStatus.PLANNING,
    (
        AssistantStatus.PLANNING,
        AssistantEvent.PREVIEW_READY,
    ): AssistantStatus.PLAN_READY,
    (AssistantStatus.IDLE, AssistantEvent.PREVIEW_READY): AssistantStatus.PLAN_READY,
    (AssistantStatus.SUCCESS, AssistantEvent.PREVIEW_READY): AssistantStatus.PLAN_READY,
    (AssistantStatus.ERROR, AssistantEvent.PREVIEW_READY): AssistantStatus.PLAN_READY,
    (
        AssistantStatus.PLAN_READY,
        AssistantEvent.EXECUTION_STARTED,
    ): AssistantStatus.WORKING,
    (
        AssistantStatus.WORKING,
        AssistantEvent.EXECUTION_SUCCEEDED,
    ): AssistantStatus.SUCCESS,
}

_PRESENTATIONS = {
    AssistantStatus.IDLE: AssistantPresentation(
        label="待机",
        detail="告诉我想怎样调整场景",
        icon="OUTLINER_OB_LIGHT",
        color=(0.15, 0.72, 0.86),
    ),
    AssistantStatus.AI_REVIEW: AssistantPresentation(
        label="等待数据确认",
        detail="请检查本轮将发送给模型的数据",
        icon="VIEWZOOM",
        color=(0.72, 0.52, 0.95),
    ),
    AssistantStatus.PLANNING: AssistantPresentation(
        label="AI 正在规划",
        detail="正在等待结构化候选计划，场景尚未修改",
        icon="TIME",
        color=(0.55, 0.42, 0.95),
    ),
    AssistantStatus.PLAN_READY: AssistantPresentation(
        label="等待确认",
        detail="计划已生成，场景尚未修改",
        icon="PREVIEW_RANGE",
        color=(0.95, 0.58, 0.12),
    ),
    AssistantStatus.WORKING: AssistantPresentation(
        label="正在工作",
        detail="正在通过安全执行层修改场景",
        icon="TIME",
        color=(0.25, 0.62, 1.0),
    ),
    AssistantStatus.SUCCESS: AssistantPresentation(
        label="已完成",
        detail="修改已提交并通过验证",
        icon="CHECKMARK",
        color=(0.22, 0.78, 0.42),
    ),
    AssistantStatus.ERROR: AssistantPresentation(
        label="需要处理",
        detail="操作没有完成，请查看错误说明",
        icon="ERROR",
        color=(0.92, 0.22, 0.18),
    ),
}


def next_status(current: AssistantStatus, event: AssistantEvent) -> AssistantStatus:
    """返回下一状态；拒绝会误导用户的非法状态跳转。"""

    if event is AssistantEvent.CLEARED:
        return AssistantStatus.IDLE
    if event is AssistantEvent.FAILED:
        return AssistantStatus.ERROR
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError as error:
        raise ValueError(
            f"Unsupported assistant transition: {current.value} + {event.value}"
        ) from error


def presentation_for(status: AssistantStatus) -> AssistantPresentation:
    """返回状态对应的稳定中文展示。"""

    return _PRESENTATIONS[status]
