"""OpenAI-compatible 结构化规划客户端测试。"""

from __future__ import annotations

import json
import unittest

from bsa.planner.llm.openai_chat import OpenAICompatiblePlannerClient
from bsa.planner.openai_compatible import (
    ProviderConnectionConfig,
    ProviderError,
    ProviderErrorCode,
)
from bsa.planner.provider import PlannerRequest
from tests.test_plan_candidate import valid_candidate


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _amount: int) -> bytes:
        return self._payload


class _SequentialOpener:
    def __init__(self, *responses: _FakeResponse) -> None:
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout: float):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def completion(content: str, *, request_id: str, input_tokens: int, output_tokens: int):
    return _FakeResponse(
        {
            "id": request_id,
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
            },
        }
    )


def planner_request() -> PlannerRequest:
    return PlannerRequest(
        instruction="让 Lamp 靠近 Desk，保持 Desk 不动",
        scene_context={
            "context_version": "0.1",
            "unit_scale": 1.0,
            "objects": [
                {
                    "object_id": "lamp-id",
                    "name": "Lamp",
                    "type": "MESH",
                    "location": [0, 0, 0.5],
                    "dimensions": [0.4, 0.4, 1.0],
                    "locked": False,
                },
                {
                    "object_id": "desk-id",
                    "name": "Desk",
                    "type": "MESH",
                    "location": [0, 0, 0.5],
                    "dimensions": [4, 2, 1],
                    "locked": False,
                },
            ],
        },
        action_schema={"schema_version": "0.1", "allowed_actions": ["place_on"]},
    )


class OpenAIPlannerTests(unittest.TestCase):
    def test_lm_studio_uses_closed_schema_and_context_object_ids(self) -> None:
        opener = _SequentialOpener(completion(json.dumps(valid_candidate()), request_id="schema", input_tokens=1, output_tokens=1))
        config = ProviderConnectionConfig("http://127.0.0.1:1234/v1", "qwen", 8, output_format="json_schema")
        result = OpenAICompatiblePlannerClient(opener=opener).plan(config, "", planner_request())
        body = json.loads(opener.requests[0][0].data)
        response_format = body["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertIs(response_format["json_schema"]["strict"], True)
        schema = response_format["json_schema"]["schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), {"schema_version", "actions", "constraints", "user_summary"})
        action = schema["properties"]["actions"]["items"]["anyOf"][0]
        self.assertEqual(action["properties"]["type"]["const"], "place_on")
        self.assertEqual(action["properties"]["object_id"]["enum"], ["desk-id", "lamp-id"])
        self.assertFalse(action["additionalProperties"])
        self.assertEqual(result.request_count, 1)
        self.assertIsNone(opener.requests[0][0].get_header("Authorization"))

    def test_schema_mode_still_rejects_dangerous_output_after_one_repair(self) -> None:
        dangerous = valid_candidate()
        dangerous["python"] = "delete objects"
        opener = _SequentialOpener(completion(json.dumps(dangerous), request_id="bad1", input_tokens=1, output_tokens=1), completion(json.dumps(dangerous), request_id="bad2", input_tokens=1, output_tokens=1))
        config = ProviderConnectionConfig("http://127.0.0.1:1234/v1", "qwen", 8, output_format="json_schema")
        with self.assertRaises(ProviderError) as raised:
            OpenAICompatiblePlannerClient(opener=opener).plan(config, "", planner_request())
        self.assertEqual(raised.exception.code, ProviderErrorCode.OUTPUT_INVALID)
        self.assertEqual(len(opener.requests), 2)
        self.assertTrue(all(json.loads(request.data)["response_format"]["type"] == "json_schema" for request, _ in opener.requests))

    def test_unknown_output_format_fails_before_network(self) -> None:
        opener = _SequentialOpener()
        config = ProviderConnectionConfig("http://127.0.0.1:1234/v1", "qwen", 8, output_format="python")
        with self.assertRaises(ProviderError) as raised:
            OpenAICompatiblePlannerClient(opener=opener).plan(config, "", planner_request())
        self.assertEqual(raised.exception.code, ProviderErrorCode.INVALID_CONFIG)
        self.assertEqual(opener.requests, [])

    def setUp(self) -> None:
        self.config = ProviderConnectionConfig(
            "https://api.example.com/v1", "fixture-model", 8
        )

    def test_valid_json_candidate_returns_usage_and_safe_request(self) -> None:
        opener = _SequentialOpener(
            completion(
                json.dumps(valid_candidate()),
                request_id="request-1",
                input_tokens=120,
                output_tokens=40,
            )
        )
        response = OpenAICompatiblePlannerClient(opener=opener).plan(
            self.config, "sk-planner-secret", planner_request()
        )
        self.assertEqual(response.plan_payload["schema_version"], "0.1")
        self.assertEqual(response.usage.input_tokens, 120)
        self.assertEqual(response.usage.output_tokens, 40)
        self.assertEqual(response.request_count, 1)
        self.assertEqual(response.repair_count, 0)
        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, "https://api.example.com/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-planner-secret")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIn("表面摆放使用 place_on", body["messages"][0]["content"])
        self.assertIn("不要自行计算", body["messages"][0]["content"])
        self.assertIn("前=-Y", body["messages"][0]["content"])
        self.assertIn("不要给正在移动的对象添加 preserve_transform", body["messages"][0]["content"])
        self.assertIn("没有保留要求时 constraints 为空数组", body["messages"][0]["content"])
        self.assertNotIn("sk-planner-secret", json.dumps(body))
        self.assertEqual(timeout, 8)

    def test_invalid_first_output_is_repaired_once_and_usage_is_aggregated(self) -> None:
        opener = _SequentialOpener(
            completion("not-json", request_id="bad", input_tokens=10, output_tokens=5),
            completion(
                json.dumps(valid_candidate()),
                request_id="fixed",
                input_tokens=20,
                output_tokens=8,
            ),
        )
        response = OpenAICompatiblePlannerClient(opener=opener).plan(
            self.config, "secret", planner_request()
        )
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(response.request_count, 2)
        self.assertEqual(response.repair_count, 1)
        self.assertEqual(response.usage.input_tokens, 30)
        self.assertEqual(response.usage.output_tokens, 13)
        second_body = json.loads(opener.requests[1][0].data.decode("utf-8"))
        self.assertEqual(second_body["messages"][-1]["role"], "user")
        self.assertIn("修复", second_body["messages"][-1]["content"])

    def test_two_invalid_outputs_fail_with_stable_error(self) -> None:
        opener = _SequentialOpener(
            completion("bad-1", request_id="bad-1", input_tokens=1, output_tokens=1),
            completion("bad-2", request_id="bad-2", input_tokens=1, output_tokens=1),
        )
        with self.assertRaises(ProviderError) as raised:
            OpenAICompatiblePlannerClient(opener=opener).plan(
                self.config, "secret", planner_request()
            )
        self.assertEqual(raised.exception.code, ProviderErrorCode.OUTPUT_INVALID)
        self.assertEqual(len(opener.requests), 2)
        self.assertNotIn("bad-2", str(raised.exception))

    def test_planning_requires_a_model(self) -> None:
        with self.assertRaises(ProviderError) as raised:
            OpenAICompatiblePlannerClient(opener=_SequentialOpener()).plan(
                ProviderConnectionConfig("https://api.example.com/v1", "", 8),
                "secret",
                planner_request(),
            )
        self.assertEqual(raised.exception.code, ProviderErrorCode.INVALID_CONFIG)


if __name__ == "__main__":
    unittest.main()
