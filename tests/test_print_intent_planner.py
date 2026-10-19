"""OpenAI-compatible 3D 打印需求结构化候选客户端测试。"""

from __future__ import annotations

import json
import unittest

from bsa.planner.llm.print_intent_chat import OpenAICompatiblePrintIntentClient
from bsa.planner.openai_compatible import ProviderConnectionConfig, ProviderError, ProviderErrorCode
from bsa.planner.print_intent_provider import PrintIntentRequest
from bsa.core.adapter_plate import design_adapter_plate
from tests.test_adapter_plate import make_plate
from tests.test_openai_planner import _SequentialOpener, completion
from tests.test_print_intent_candidate import design_payload


def request() -> PrintIntentRequest:
    return PrintIntentRequest(
        instruction="做一块 80×40×3 mm 的转接板，设备孔距 20，支架孔距 20",
        requested_measurements=(),
        measurement_answers="",
        current_design=None,
    )


class PrintIntentPlannerTests(unittest.TestCase):
    def test_schema_mode_uses_print_candidate_schema_and_minimal_context(self) -> None:
        opener = _SequentialOpener(
            completion(
                json.dumps(design_payload()),
                request_id="print-1",
                input_tokens=40,
                output_tokens=20,
            )
        )
        config = ProviderConnectionConfig(
            "http://127.0.0.1:1234/v1", "qwen", 8, output_format="json_schema"
        )
        response = OpenAICompatiblePrintIntentClient(opener=opener).plan(
            config, "", request()
        )
        body = json.loads(opener.requests[0][0].data.decode("utf-8"))
        schema = body["response_format"]["json_schema"]["schema"]
        self.assertEqual(body["response_format"]["json_schema"]["name"], "print_intent_candidate")
        self.assertIn("oneOf", schema)
        self.assertIn("3D 打印零件需求规划器", body["messages"][0]["content"])
        self.assertIn("缺少关键尺寸", body["messages"][0]["content"])
        self.assertNotIn("scene_context", json.dumps(body, ensure_ascii=False))
        user_payload = json.loads(body["messages"][1]["content"])
        self.assertEqual(
            set(user_payload),
            {
                "instruction",
                "requested_measurements",
                "measurement_answers",
                "required_output_schema",
            },
        )
        self.assertEqual(response.plan_payload["status"], "design_candidate")

    def test_modification_request_exposes_current_design_and_requires_patch(self) -> None:
        patch = {
            "schema_version": "0.1",
            "status": "parameter_patch",
            "part_family": "adapter_plate",
            "target_plate_id": "adapter-demo",
            "patch": {
                "new_width_mm": 90.0,
                "fixed_x_edge": "right",
                "fixed_y_edge": "front",
                "preserve_pattern_ids": ["device", "support"],
            },
            "preserve_relations": ["hole_world_centers"],
            "assumptions": [],
            "user_summary": "板宽改为 90 mm，孔位不变",
        }
        opener = _SequentialOpener(
            completion(
                json.dumps(patch),
                request_id="patch-1",
                input_tokens=30,
                output_tokens=20,
            )
        )
        current = design_adapter_plate(make_plate())
        response = OpenAICompatiblePrintIntentClient(opener=opener).plan(
            ProviderConnectionConfig(
                "http://127.0.0.1:1234/v1",
                "qwen",
                8,
                output_format="json_schema",
            ),
            "",
            PrintIntentRequest(
                instruction="板加长 10 mm，所有孔的位置保持不变",
                requested_measurements=(),
                measurement_answers="",
                current_design=current.to_dict(),
            ),
        )
        body = json.loads(opener.requests[0][0].data.decode("utf-8"))
        user_payload = json.loads(body["messages"][1]["content"])
        self.assertEqual(user_payload["current_design"]["plate_id"], "adapter-demo")
        self.assertIn("parameter_patch", body["messages"][0]["content"])
        self.assertEqual(response.plan_payload["status"], "parameter_patch")

    def test_invalid_candidate_is_repaired_once(self) -> None:
        opener = _SequentialOpener(
            completion("not-json", request_id="bad", input_tokens=4, output_tokens=2),
            completion(
                json.dumps(design_payload()),
                request_id="fixed",
                input_tokens=8,
                output_tokens=4,
            ),
        )
        response = OpenAICompatiblePrintIntentClient(opener=opener).plan(
            ProviderConnectionConfig("https://api.example.com/v1", "fixture", 8),
            "secret",
            request(),
        )
        self.assertEqual(response.request_count, 2)
        self.assertEqual(response.repair_count, 1)
        self.assertEqual(response.usage.input_tokens, 12)
        second = json.loads(opener.requests[1][0].data.decode("utf-8"))
        self.assertIn("修复", second["messages"][-1]["content"])

    def test_two_invalid_candidates_fail_without_executing_anything(self) -> None:
        opener = _SequentialOpener(
            completion("bad", request_id="bad-1", input_tokens=1, output_tokens=1),
            completion("still bad", request_id="bad-2", input_tokens=1, output_tokens=1),
        )
        with self.assertRaises(ProviderError) as raised:
            OpenAICompatiblePrintIntentClient(opener=opener).plan(
                ProviderConnectionConfig("https://api.example.com/v1", "fixture", 8),
                "secret",
                request(),
            )
        self.assertEqual(raised.exception.code, ProviderErrorCode.OUTPUT_INVALID)


if __name__ == "__main__":
    unittest.main()

