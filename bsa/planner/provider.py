"""与具体模型厂商无关的规划 Provider 契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class PlannerRequest:
    """发送给规划器的最小只读输入。"""

    instruction: str
    scene_context: Mapping[str, Any]
    action_schema: Mapping[str, Any]


@dataclass(frozen=True)
class PlannerUsage:
    """一次规划调用的可选用量信息。"""

    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: float | None
    latency_ms: int


@dataclass(frozen=True)
class PlannerResponse:
    """Provider 返回的结构化候选计划；执行前仍需本地严格校验。"""

    plan_payload: Mapping[str, Any]
    usage: PlannerUsage
    request_id: str | None
    request_count: int
    repair_count: int


@runtime_checkable
class PlannerProvider(Protocol):
    """所有远程或本地模型规划器都必须遵守的最小接口。"""

    def plan(self, request: PlannerRequest) -> PlannerResponse:
        """把自然语言和最小场景上下文转换为候选计划。"""
