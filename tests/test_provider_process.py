"""Provider 子进程隔离与取消测试。"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bsa.infra.provider_process import ProviderWorkerTask
from bsa.planner.openai_compatible import ProviderConnectionConfig, ProviderErrorCode
from bsa.planner.print_intent_provider import PrintIntentRequest
from bsa.planner.provider import PlannerRequest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKER_SCRIPT = REPOSITORY_ROOT / "bsa" / "planner" / "llm" / "worker.py"


class _ModelHandler(BaseHTTPRequestHandler):
    authorization = ""
    delay_seconds = 0.0
    request_body = {}

    def do_GET(self) -> None:  # noqa: N802 - 标准库回调名
        type(self).authorization = self.headers.get("Authorization", "")
        if type(self).delay_seconds:
            time.sleep(type(self).delay_seconds)
        payload = json.dumps({"data": [{"id": "fixture-model"}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802 - 标准库回调名
        type(self).authorization = self.headers.get("Authorization", "")
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_body = json.loads(self.rfile.read(length).decode("utf-8"))
        system_text = type(self).request_body["messages"][0]["content"]
        if "3D 打印零件需求规划器" in system_text:
            candidate = {
                "schema_version": "0.1",
                "status": "needs_input",
                "part_family": "adapter_plate",
                "missing_measurements": [
                    {
                        "measurement_id": "plate_width",
                        "measurement_type": "outer_width",
                        "target_id": "adapter_plate",
                        "label": "可用板宽",
                        "reason": "确定板件外形",
                        "unit": "mm",
                    }
                ],
                "assumptions": [],
                "user_summary": "需要补充板宽",
            }
        else:
            candidate = {
                "schema_version": "0.1",
                "actions": [
                    {
                        "action_id": "lock-1",
                        "type": "lock",
                        "object_id": "desk-id",
                    }
                ],
                "constraints": [],
                "user_summary": "锁定 Desk",
            }
        payload = json.dumps(
            {
                "id": "worker-request",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(candidate),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 22, "completion_tokens": 9},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _wait_for(task: ProviderWorkerTask, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        outcome = task.poll()
        if outcome is not None:
            return outcome
        time.sleep(0.01)
    raise AssertionError("provider worker did not complete")


class ProviderProcessTests(unittest.TestCase):
    def test_planning_worker_transmits_schema_mode_without_key(self) -> None:
        base_config = self._config()
        config = ProviderConnectionConfig(base_config.api_base, base_config.model, 3, "json_schema")
        request = PlannerRequest("保护 Desk", {"objects": [{"object_id": "desk-id"}]}, {"allowed_actions": ["lock"]})
        task = ProviderWorkerTask.start_plan(config, "", request, python_executable=Path(sys.executable), worker_script=WORKER_SCRIPT)
        outcome = _wait_for(task)
        self.assertTrue(outcome.ok, outcome)
        response_format = _ModelHandler.request_body["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        action = response_format["json_schema"]["schema"]["properties"]["actions"]["items"]["anyOf"][0]
        self.assertEqual(action["properties"]["type"]["const"], "lock")
        self.assertEqual(_ModelHandler.authorization, "")

    def setUp(self) -> None:
        _ModelHandler.authorization = ""
        _ModelHandler.delay_seconds = 0.0
        _ModelHandler.request_body = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _config(self, *, timeout: int = 3) -> ProviderConnectionConfig:
        host, port = self.server.server_address
        return ProviderConnectionConfig(
            f"http://{host}:{port}/v1",
            "fixture-model",
            timeout,
        )

    def test_worker_receives_key_over_stdin_not_command_line(self) -> None:
        secret = "sk-process-secret"
        task = ProviderWorkerTask.start(
            self._config(),
            secret,
            python_executable=Path(sys.executable),
            worker_script=WORKER_SCRIPT,
        )
        self.assertNotIn(secret, " ".join(task.command))
        self.assertNotIn(secret, repr(task))
        outcome = _wait_for(task)
        self.assertTrue(outcome.ok, outcome)
        self.assertEqual(outcome.result["models"], ["fixture-model"])
        self.assertEqual(_ModelHandler.authorization, f"Bearer {secret}")
        self.assertNotIn(secret, json.dumps(outcome.to_dict()))

    def test_cancel_returns_stable_error(self) -> None:
        _ModelHandler.delay_seconds = 2.0
        task = ProviderWorkerTask.start(
            self._config(timeout=5),
            "cancel-secret",
            python_executable=Path(sys.executable),
            worker_script=WORKER_SCRIPT,
        )
        outcome = task.cancel()
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error["code"], ProviderErrorCode.CANCELED.value)
        self.assertIsNotNone(task.poll())

    def test_planning_worker_returns_candidate_without_exposing_key(self) -> None:
        secret = "sk-planning-process-secret"
        request = PlannerRequest(
            instruction="保护桌子",
            scene_context={
                "context_version": "0.1",
                "unit_scale": 1.0,
                "objects": [
                    {
                        "object_id": "desk-id",
                        "name": "Desk",
                        "type": "MESH",
                        "location": [0, 0, 0.5],
                        "dimensions": [4, 2, 1],
                        "locked": False,
                    }
                ],
            },
            action_schema={"schema_version": "0.1", "allowed_actions": ["lock"]},
        )
        task = ProviderWorkerTask.start_plan(
            self._config(),
            secret,
            request,
            python_executable=Path(sys.executable),
            worker_script=WORKER_SCRIPT,
        )
        self.assertNotIn(secret, " ".join(task.command))
        outcome = _wait_for(task)
        self.assertTrue(outcome.ok, outcome)
        self.assertEqual(outcome.result["plan_payload"]["actions"][0]["type"], "lock")
        self.assertEqual(outcome.result["usage"]["input_tokens"], 22)
        self.assertEqual(outcome.result["request_count"], 1)
        self.assertNotIn(secret, json.dumps(outcome.to_dict()))
        self.assertEqual(_ModelHandler.authorization, f"Bearer {secret}")
        self.assertNotIn(secret, json.dumps(_ModelHandler.request_body))

    def test_print_intent_worker_returns_strict_candidate(self) -> None:
        secret = "sk-print-process-secret"
        request = PrintIntentRequest(
            instruction="做一个连接设备与支架的转接板",
            requested_measurements=(),
            measurement_answers="",
        )
        task = ProviderWorkerTask.start_print_intent(
            self._config(),
            secret,
            request,
            python_executable=Path(sys.executable),
            worker_script=WORKER_SCRIPT,
        )
        self.assertNotIn(secret, " ".join(task.command))
        outcome = _wait_for(task)
        self.assertTrue(outcome.ok, outcome)
        self.assertEqual(outcome.result["plan_payload"]["status"], "needs_input")
        self.assertEqual(outcome.result["plan_payload"]["part_family"], "adapter_plate")
        self.assertNotIn(secret, json.dumps(outcome.to_dict()))
        request_body = _ModelHandler.request_body
        self.assertNotIn("scene_context", json.dumps(request_body, ensure_ascii=False))
        self.assertEqual(_ModelHandler.authorization, f"Bearer {secret}")


if __name__ == "__main__":
    unittest.main()
