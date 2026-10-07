"""真实模型评测的 HTTP 总请求上限。"""

from __future__ import annotations

from typing import Any


class RequestBudgetExceeded(RuntimeError):
    """总请求预算用完时，在发出下一次 HTTP 请求前停止。"""


class RequestBudgetOpener:
    """包装网络接口；修复请求也占用同一预算。"""

    def __init__(self, opener: Any, max_requests: int) -> None:
        if isinstance(max_requests, bool) or not 1 <= max_requests <= 100:
            raise ValueError("请求上限必须在 1 到 100 之间")
        self._opener = opener
        self.max_requests = max_requests
        self.request_count = 0

    def open(self, request: Any, timeout: float) -> Any:
        """预算检查发生在任何网络访问之前。"""
        if self.request_count >= self.max_requests:
            raise RequestBudgetExceeded("真实模型请求预算已经用完")
        self.request_count += 1
        return self._opener.open(request, timeout=timeout)
