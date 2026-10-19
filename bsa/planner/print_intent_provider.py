"""3D 打印零件需求规划器的最小只读请求。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PrintIntentRequest:
    """只包含用户主动提供的需求、待回答问题和补充答案。"""

    instruction: str
    requested_measurements: tuple[Mapping[str, Any], ...]
    measurement_answers: str
    current_design: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "instruction": self.instruction,
            "requested_measurements": [dict(item) for item in self.requested_measurements],
            "measurement_answers": self.measurement_answers,
        }
        if self.current_design is not None:
            payload["current_design"] = dict(self.current_design)
        return payload

