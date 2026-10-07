"""在 Blender 中用本地模拟服务验证 Provider 连接与取消闭环。"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bpy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def load_extension():
    module_name = "blender_scene_assistant_provider_integration"
    spec = importlib.util.spec_from_file_location(
        module_name,
        REPOSITORY_ROOT / "__init__.py",
        submodule_search_locations=[str(REPOSITORY_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load extension package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class ProviderHandler(BaseHTTPRequestHandler):
    """只提供测试所需的模型列表；不记录请求正文。"""

    authorization = ""
    post_count = 0
    post_delay_seconds = 0.0
    planning_request = {}
    expected_output_format = "json_object"

    def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
        type(self).authorization = self.headers.get("Authorization", "")
        if self.path.startswith("/slow/"):
            time.sleep(2.0)
        payload = json.dumps(
            {"data": [{"id": "scene-planner-test"}, {"id": "fallback-test"}]}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:  # noqa: N802 - HTTP handler API
        type(self).authorization = self.headers.get("Authorization", "")
        type(self).post_count += 1
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).planning_request = body
        if body.get("response_format", {}).get("type") != type(self).expected_output_format:
            raise AssertionError("UI did not send the selected output format")
        if type(self).post_delay_seconds:
            time.sleep(type(self).post_delay_seconds)
        user_payload = json.loads(body["messages"][1]["content"])
        objects = {
            item["name"]: item["object_id"]
            for item in user_payload["scene_context"]["objects"]
        }
        candidate = {
            "schema_version": "0.1",
            "actions": [
                {
                    "action_id": "place-1",
                    "type": "place_on",
                    "object_id": objects["Lamp"],
                    "target_id": objects["Desk"],
                    "region": "right",
                    "clearance": 0.0,
                }
            ],
            "constraints": [
                {
                    "constraint_id": "preserve-1",
                    "type": "preserve_transform",
                    "object_id": objects["Desk"],
                    "severity": "hard",
                }
            ],
            "user_summary": "本轮只查看场景，不移动任何物体",
        }
        payload = json.dumps(
            {
                "id": "blender-ai-plan-request",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(candidate),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 80, "completion_tokens": 35},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format: str, *_args: object) -> None:
        return


def wait_for_connection(operators_module: object, session: object) -> None:
    deadline = time.monotonic() + 8.0
    while session.connection_status == "TESTING" and time.monotonic() < deadline:
        operators_module._poll_provider_task()
        time.sleep(0.05)
    if session.connection_status == "TESTING":
        raise AssertionError("Provider UI task did not finish before the test deadline")


def wait_for_planning(operators_module: object, settings: object) -> None:
    deadline = time.monotonic() + 8.0
    while settings.assistant_status == "PLANNING" and time.monotonic() < deadline:
        operators_module._poll_ai_task()
        time.sleep(0.05)
    if settings.assistant_status == "PLANNING":
        raise AssertionError("AI planning task did not finish before the test deadline")


def add_cube(name: str, location: tuple[float, float, float], scale: tuple[float, float, float]):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.context.view_layer.update()
    return obj


def scene_state() -> tuple[tuple[str, tuple[float, ...]], ...]:
    return tuple(
        (obj.name, tuple(round(value, 6) for row in obj.matrix_world for value in row))
        for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name)
    )


def main() -> int:
    if not bpy.app.online_access:
        raise AssertionError("Run this suite with Blender --online-mode")

    server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
    server.daemon_threads = True
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    extension = None
    registered = False
    try:
        if hasattr(bpy.types.WindowManager, "bsa_provider_session"):
            from bl_ext.user_default.blender_scene_assistant.bsa.ui import operators
        else:
            extension = load_extension()
            extension.register()
            registered = True
            from blender_scene_assistant_provider_integration.bsa.ui import operators

        session = bpy.context.window_manager.bsa_provider_session
        settings = bpy.context.scene.bsa_settings
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        desk = add_cube("Desk", (0.0, 0.0, 0.5), (2.0, 1.0, 0.5))
        lamp = add_cube("Lamp", (0.0, 0.0, 0.5), (0.2, 0.2, 0.5))
        before = scene_state()
        session.api_base = f"http://127.0.0.1:{server.server_port}/v1"
        session.model = "scene-planner-test"
        session.api_key = "sk-local-provider-ui-probe"
        session.timeout_seconds = 5
        if "--json-schema" in sys.argv:
            session.output_format = "json_schema"
            ProviderHandler.expected_output_format = "json_schema"

        if bpy.ops.bsa.test_provider_connection() != {"FINISHED"}:
            raise AssertionError("Provider connection test did not start")
        if session.connection_status != "TESTING":
            raise AssertionError("Provider UI did not enter testing state")
        wait_for_connection(operators, session)
        if session.connection_status != "SUCCESS":
            raise AssertionError(f"Provider connection failed: {session.connection_message}")
        if "模型可用" not in session.connection_message:
            raise AssertionError("Selected model availability was not shown")
        if ProviderHandler.authorization != "Bearer sk-local-provider-ui-probe":
            raise AssertionError("Provider worker did not use the session credential")
        if scene_state() != before or settings.plan_json:
            raise AssertionError("Successful connection test changed the scene or created a plan")

        session.api_base = f"http://127.0.0.1:{server.server_port}/slow"
        if bpy.ops.bsa.test_provider_connection() != {"FINISHED"}:
            raise AssertionError("Cancelable Provider test did not start")
        if bpy.ops.bsa.cancel_provider_connection() != {"FINISHED"}:
            raise AssertionError("Provider cancellation operator failed")
        if session.connection_status != "CANCELED":
            raise AssertionError("Provider UI did not show the canceled state")
        if scene_state() != before or settings.plan_json:
            raise AssertionError("Canceled connection test changed the scene or created a plan")

        class FailingPollTask:
            def __init__(self) -> None:
                self.canceled = False

            def poll(self):
                raise RuntimeError("synthetic poll failure")

            def cancel(self):
                self.canceled = True

        failing_task = FailingPollTask()
        operators._PROVIDER_TASK = failing_task
        operators._PROVIDER_TIMER_ACTIVE = True
        session.connection_status = "TESTING"
        operators._poll_provider_task()
        if session.connection_status != "ERROR":
            raise AssertionError("Provider poll failure was not shown as an error")
        if operators._PROVIDER_TASK is not None or operators._PROVIDER_TIMER_ACTIVE:
            raise AssertionError("Provider poll failure did not release the task")
        if not failing_task.canceled:
            raise AssertionError("Provider poll failure did not cancel the worker")
        if scene_state() != before or settings.plan_json:
            raise AssertionError("Provider poll failure changed the scene or created a plan")

        session.api_base = f"http://127.0.0.1:{server.server_port}/v1"
        session.model = "scene-planner-test"
        ProviderHandler.post_count = 0
        settings.instruction = "重新安排 Lamp 和 Desk，让画面更紧凑"
        if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
            raise AssertionError("AI request did not enter data review")
        if settings.assistant_status != "AI_REVIEW":
            raise AssertionError("AI request skipped data review")
        if ProviderHandler.post_count != 0:
            raise AssertionError("AI network request started before user approval")
        review_payload = json.loads(session.pending_context_json)
        summaries = review_payload["scene_context"]["objects"]
        if {item["name"] for item in summaries} != {"Desk", "Lamp"}:
            raise AssertionError("AI context did not contain exactly the named objects")
        expected_fields = {"object_id", "name", "type", "location", "dimensions", "locked"}
        if any(set(item) != expected_fields for item in summaries):
            raise AssertionError("AI context leaked fields outside the privacy contract")
        if bpy.ops.bsa.start_ai_planning() != {"FINISHED"}:
            raise AssertionError("Approved AI planning did not start")
        if settings.assistant_status != "PLANNING":
            raise AssertionError("Assistant did not show planning state")
        wait_for_planning(operators, settings)
        if settings.assistant_status != "PLAN_READY" or not settings.plan_json:
            raise AssertionError(f"AI plan was not previewed: {settings.last_assistant_message}")
        ai_plan = json.loads(settings.plan_json)
        if ai_plan["source"] != "llm" or not ai_plan["requires_confirmation"]:
            raise AssertionError("AI plan did not receive trusted local fields")
        if "实际执行动作" not in settings.preview_text or "Lamp 放到 Desk 的右侧" not in settings.preview_text:
            raise AssertionError("AI summary hid the actual placement action in preview")
        if "保持 Desk 的变换不动" not in settings.preview_text:
            raise AssertionError("AI preview did not show the actual protection constraint")
        if scene_state() != before:
            raise AssertionError("AI planning changed the scene before confirmation")
        if session.last_input_tokens != 80 or session.last_output_tokens != 35:
            raise AssertionError("AI usage was not shown in the session")
        if session.last_request_count != 1 or session.last_repair_count != 0:
            raise AssertionError("AI request counters are incorrect")
        if ProviderHandler.post_count != 1:
            raise AssertionError("AI planning used an unexpected number of requests")
        if bpy.ops.bsa.confirm_plan() != {"FINISHED"}:
            raise AssertionError("Confirmed AI plan did not execute")
        execution = json.loads(settings.result_json)
        if execution["status"] != "COMMITTED" or not execution["verification"]["passed"]:
            raise AssertionError("AI plan execution did not pass local verification")
        if tuple(desk.matrix_world.translation) != (0.0, 0.0, 0.5):
            raise AssertionError("AI plan changed the preserved Desk")
        if tuple(lamp.matrix_world.translation) == (0.0, 0.0, 0.5):
            raise AssertionError("Confirmed AI plan did not move Lamp")

        after_ai_execution = scene_state()
        ProviderHandler.post_delay_seconds = 2.0
        settings.instruction = "再次重新安排 Lamp 和 Desk，让画面更紧凑"
        if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
            raise AssertionError("Cancelable AI request did not enter data review")
        if bpy.ops.bsa.start_ai_planning() != {"FINISHED"}:
            raise AssertionError("Cancelable AI planning did not start")
        if bpy.ops.bsa.cancel_ai_planning() != {"FINISHED"}:
            raise AssertionError("AI planning cancellation operator failed")
        if settings.assistant_status != "ERROR" or settings.plan_json:
            raise AssertionError("Canceled AI planning left an executable plan")
        if scene_state() != after_ai_execution:
            raise AssertionError("Canceled AI planning changed the scene")

        ProviderHandler.post_delay_seconds = 0.35
        settings.instruction = "重新安排 Desk 和 Lamp，让主体关系更紧凑"
        if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
            raise AssertionError("Stale AI request did not enter data review")
        if bpy.ops.bsa.start_ai_planning() != {"FINISHED"}:
            raise AssertionError("Stale AI planning did not start")
        lamp_before_stale = tuple(lamp.matrix_world.translation)
        desk.location.x += 0.25
        bpy.context.view_layer.update()
        desk_after_user_change = tuple(desk.matrix_world.translation)
        wait_for_planning(operators, settings)
        if settings.assistant_status != "ERROR" or settings.plan_json:
            raise AssertionError("Stale AI result was not rejected")
        if "场景已改变" not in settings.result_text:
            raise AssertionError("Stale AI result did not explain the cause")
        if tuple(desk.matrix_world.translation) != desk_after_user_change:
            raise AssertionError("Stale rejection reverted the user's scene edit")
        if tuple(lamp.matrix_world.translation) != lamp_before_stale:
            raise AssertionError("Stale AI result changed an object")
        ProviderHandler.post_delay_seconds = 0.0

        report = {
            "blender_version": bpy.app.version_string,
            "extension_version": importlib.import_module(operators.__package__.rsplit(".ui", 1)[0]).__version__,
            "online_mode": bpy.app.online_access,
            "connection_status": "SUCCESS",
            "selected_model_available": True,
            "cancellation_status": "CANCELED",
            "scene_unchanged": True,
            "plan_not_created": True,
            "poll_failure_cleaned_up": True,
            "ai_data_review_required": True,
            "ai_plan_previewed_before_execution": True,
            "ai_plan_verified_after_confirmation": True,
            "ai_planning_cancel_is_read_only": True,
            "ai_stale_result_rejected": True,
            "trusted_action_preview_passed": True,
            "output_format": session.output_format,
            "installed_package": extension is None,
        }
        output = REPOSITORY_ROOT / "benchmarks" / "results" / "m2_provider_ui_results.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("BSA_PROVIDER_UI_RESULT=" + json.dumps(report, ensure_ascii=True))
        return 0
    finally:
        if registered and extension is not None:
            extension.unregister()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
