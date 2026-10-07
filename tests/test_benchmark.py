"""固定任务评测必须独立于模型计划自己的验证结果。"""

import unittest
from copy import deepcopy
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch
import json

from benchmarks.evaluation import evaluate_case, load_suite, replay_suite, review_case, summarize
from benchmarks.live import RequestBudgetOpener, RequestBudgetExceeded
from bsa.planner.provider import PlannerResponse, PlannerUsage
from benchmarks.runner import main


def response(payload):
    return PlannerResponse(payload, PlannerUsage("fixture", "replay", None, None, None, 0), None, 0, 0)


class BenchmarkTests(unittest.TestCase):
    def test_default_runner_is_read_only_and_never_calls_network(self) -> None:
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("意外联网")), patch.object(Path, "write_text") as write, redirect_stdout(StringIO()):
            self.assertEqual(main(["--case", "ai_01"]), 0)
        report = json.loads(write.call_args.args[0])
        self.assertEqual(report["mode"], "review")
        self.assertEqual(report["network_request_count"], 0)

    def test_live_runner_limits_calls_and_does_not_report_unrun_tasks_as_accuracy(self) -> None:
        suite = load_suite()
        payload = {"choices": [{"message": {"content": json.dumps(suite["replay_plans"]["place_right"])}, "finish_reason": "stop"}]}
        class FakeOpener:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                return BytesIO(json.dumps(payload).encode("utf-8"))
        inner = FakeOpener()
        with patch("urllib.request.build_opener", return_value=inner), patch.object(Path, "write_text") as write, redirect_stdout(StringIO()):
            status = main(["--mode", "live", "--api-base", "http://127.0.0.1/v1", "--model", "test", "--max-requests", "1", "--case", "ai_01", "--case", "ai_03"])
        report = json.loads(write.call_args.args[0])
        self.assertEqual(status, 0)
        self.assertEqual(inner.calls, 1)
        self.assertEqual(report["network_request_count"], 1)
        self.assertEqual(report["skipped_count"], 1)
        self.assertEqual(report["measured_ai_task_count"], 1)
        self.assertEqual(report["real_model_success_rate"], 1.0)

    def test_skipped_tasks_are_not_measured_model_failures(self) -> None:
        suite = load_suite()
        case = next(item for item in suite["cases"] if item["case_id"] == "ai_01")
        def exhausted(request):
            raise RequestBudgetExceeded()
        result = evaluate_case(case, planner=exhausted, mode="live")
        report = summarize(suite, [result], mode="live")
        self.assertEqual(report["skipped_count"], 1)
        self.assertEqual(report["measured_ai_task_count"], 0)
        self.assertIsNone(report["real_model_success_rate"])

    def test_twenty_fixed_tasks_have_separate_success_and_rejection_metrics(self) -> None:
        suite = load_suite()
        self.assertEqual(len(suite["cases"]), 20)
        report = replay_suite(suite)
        self.assertEqual(report["mode"], "replay")
        self.assertEqual(report["task_success_count"], 16)
        self.assertEqual(report["expected_rejection_count"], 4)
        self.assertEqual(report["passed_count"], 20)
        self.assertEqual(report["network_request_count"], 0)
        self.assertIsNone(report["real_model_success_rate"])

    def test_wrong_direction_commits_but_fails_user_goal(self) -> None:
        suite = load_suite()
        case = next(item for item in suite["cases"] if item["case_id"] == "ai_05")
        payload = deepcopy(suite["replay_plans"][case["replay_key"]])
        payload["actions"][0]["delta"] = [-0.2, 0, 0]
        result = evaluate_case(case, planner=lambda request: response(payload), mode="replay")
        self.assertEqual(result["execution_status"], "COMMITTED")
        self.assertFalse(result["task_success"])
        self.assertFalse(result["passed"])

    def test_extra_authorized_plan_action_is_unauthorized_by_user_task(self) -> None:
        suite = load_suite()
        case = next(item for item in suite["cases"] if item["case_id"] == "ai_05")
        payload = deepcopy(suite["replay_plans"][case["replay_key"]])
        # 本例指令同时提到 Desk，确保它在模型上下文里；事务会允许计划的 affected set。
        payload["actions"].append({"action_id": "extra", "type": "move", "object_id": "desk-id", "delta": [0.5, 0, 0], "space": "world"})
        result = evaluate_case(case, planner=lambda request: response(payload), mode="replay")
        self.assertEqual(result["execution_status"], "COMMITTED")
        self.assertEqual(result["task_unauthorized_changes"], ["desk-id"])
        self.assertFalse(result["passed"])

    def test_review_does_not_call_provider_and_excludes_expected_answers(self) -> None:
        suite = load_suite()
        case = next(item for item in suite["cases"] if item["case_id"] == "ai_01")
        review = review_case(case)
        self.assertEqual(review["route"], "ai")
        self.assertNotIn("goals", review["request"])
        self.assertNotIn("replay_key", review["request"])
        self.assertEqual(set(review["request"]), {"instruction", "scene_context", "action_schema"})

    def test_request_budget_blocks_before_opening_network(self) -> None:
        class FakeOpener:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                return "opened"
        inner = FakeOpener()
        bounded = RequestBudgetOpener(inner, 2)
        self.assertEqual(bounded.open("first", 1), "opened")
        self.assertEqual(bounded.open("repair", 1), "opened")
        with self.assertRaises(RequestBudgetExceeded):
            bounded.open("third", 1)
        self.assertEqual(inner.calls, 2)
        self.assertEqual(bounded.request_count, 2)


if __name__ == "__main__":
    unittest.main()
