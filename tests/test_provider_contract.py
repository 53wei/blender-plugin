"""Provider 中立契约测试。"""

from __future__ import annotations

import unittest

from bsa.planner.provider import (
    PlannerProvider,
    PlannerRequest,
    PlannerResponse,
    PlannerUsage,
)


class _FakeProvider:
    def plan(self, request: PlannerRequest) -> PlannerResponse:
        return PlannerResponse(
            plan_payload={"schema_version": "0.1", "actions": []},
            usage=PlannerUsage(
                provider="fake",
                model="fixture-model",
                input_tokens=10,
                output_tokens=5,
                estimated_cost=None,
                latency_ms=12,
            ),
            request_id="fixture-request",
            request_count=1,
            repair_count=0,
        )


class ProviderContractTests(unittest.TestCase):
    def test_provider_contract_is_provider_neutral(self) -> None:
        provider: PlannerProvider = _FakeProvider()
        request = PlannerRequest(
            instruction="把灯放到桌面右侧",
            scene_context={"objects": []},
            action_schema={"schema_version": "0.1"},
        )
        response = provider.plan(request)
        self.assertEqual(response.usage.provider, "fake")
        self.assertEqual(response.plan_payload["schema_version"], "0.1")
        self.assertEqual(response.request_count, 1)

    def test_request_and_response_are_immutable(self) -> None:
        request = PlannerRequest("锁定 Desk", {}, {})
        with self.assertRaises((AttributeError, TypeError)):
            request.instruction = "changed"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
