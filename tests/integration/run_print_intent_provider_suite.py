"""在 Blender 4.5 中通过本机模拟服务验证打印件 AI 真实请求闭环。"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[2]
INSTALLED = "--installed" in sys.argv


def load_extension():
    module_name = "blender_scene_assistant_print_intent_provider"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载扩展包")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def needs_input_payload():
    return {
        "schema_version": "0.1",
        "status": "needs_input",
        "part_family": "adapter_plate",
        "missing_measurements": [
            {
                "measurement_id": "dimensions",
                "measurement_type": "outer_width",
                "target_id": "adapter_plate",
                "label": "板宽与其他关键尺寸",
                "reason": "不能把界面示例当成真实测量",
                "unit": "mm",
            }
        ],
        "assumptions": [],
        "user_summary": "需要用户补充真实毫米尺寸",
    }


def design_payload():
    return {
        "schema_version": "0.1",
        "status": "design_candidate",
        "part_family": "adapter_plate",
        "design": {
            "plate_id": "adapter-live-001",
            "width_mm": 80.0,
            "depth_mm": 40.0,
            "thickness_mm": 3.0,
            "corner_radius_mm": 2.0,
            "mounting_patterns": [
                {
                    "pattern_id": "device",
                    "origin_x_mm": 20.0,
                    "origin_y_mm": 20.0,
                    "holes": [
                        {
                            "hole_id": "device-left",
                            "offset_x_mm": -10.0,
                            "offset_y_mm": 0.0,
                            "diameter_mm": 3.2,
                        },
                        {
                            "hole_id": "device-right",
                            "offset_x_mm": 10.0,
                            "offset_y_mm": 0.0,
                            "diameter_mm": 3.2,
                        },
                    ],
                },
                {
                    "pattern_id": "support",
                    "origin_x_mm": 40.0,
                    "origin_y_mm": 20.0,
                    "holes": [
                        {
                            "hole_id": "support-front",
                            "offset_x_mm": 0.0,
                            "offset_y_mm": -10.0,
                            "diameter_mm": 4.2,
                        },
                        {
                            "hole_id": "support-back",
                            "offset_x_mm": 0.0,
                            "offset_y_mm": 10.0,
                            "diameter_mm": 4.2,
                        },
                    ],
                },
            ],
        },
        "assumptions": ["尺寸由用户在第二轮提供"],
        "user_summary": "形成可确认的四孔转接板候选",
    }


def parameter_patch_payload():
    return {
        "schema_version": "0.1",
        "status": "parameter_patch",
        "part_family": "adapter_plate",
        "target_plate_id": "adapter-live-001",
        "patch": {
            "new_width_mm": 90.0,
            "fixed_x_edge": "right",
            "fixed_y_edge": "front",
            "preserve_pattern_ids": ["device", "support"],
        },
        "preserve_relations": ["hole_world_centers"],
        "assumptions": [],
        "user_summary": "板宽改为 90 mm，全部孔位保持不变",
    }


class PrintIntentHandler(BaseHTTPRequestHandler):
    request_bodies: list[dict[str, object]] = []
    authorizations: list[str] = []

    def do_POST(self) -> None:  # noqa: N802 - 标准库回调名
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).request_bodies.append(body)
        type(self).authorizations.append(self.headers.get("Authorization", ""))
        request_count = len(type(self).request_bodies)
        if request_count == 1:
            candidate = needs_input_payload()
        elif request_count == 2:
            candidate = design_payload()
        else:
            candidate = parameter_patch_payload()
        payload = json.dumps(
            {
                "id": f"print-{len(type(self).request_bodies)}",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": json.dumps(candidate)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 20},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def wait_for_stage(settings, operators, expected: str, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while settings.stage == "AI_WORKING" and time.monotonic() < deadline:
        operators._poll_print_ai_task()
        time.sleep(0.05)
    if settings.stage != expected:
        raise AssertionError(f"等待 {expected} 失败，实际为 {settings.stage}: {settings.ai_message}")


def main() -> None:
    if not getattr(bpy.app, "online_access", False):
        raise AssertionError("测试必须使用 Blender --online-mode")
    PrintIntentHandler.request_bodies = []
    PrintIntentHandler.authorizations = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), PrintIntentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    extension = None
    if INSTALLED:
        import addon_utils

        addon_utils.enable(
            "bl_ext.user_default.blender_scene_assistant",
            default_set=False,
            persistent=False,
        )
        package = "bl_ext.user_default.blender_scene_assistant.bsa"
    else:
        extension = load_extension()
        extension.register()
        package = "blender_scene_assistant_print_intent_provider.bsa"
    try:
        operators = importlib.import_module(package + ".ui.adapter_plate_operators")
        settings = bpy.context.scene.bsa_adapter_plate_settings
        session = bpy.context.window_manager.bsa_provider_session
        host, port = server.server_address
        session.api_base = f"http://{host}:{port}/v1"
        session.model = "fixture-print-model"
        session.output_format = "json_schema"
        session.api_key = ""
        settings.ai_instruction = "我要把设备固定到支架，但两边孔位不同"
        object_count = len(bpy.context.scene.objects)

        if bpy.ops.bsa.prepare_print_intent() != {"FINISHED"}:
            raise AssertionError("第一轮数据准备失败")
        if PrintIntentHandler.request_bodies:
            raise AssertionError("发送确认前发生了网络请求")
        if bpy.ops.bsa.start_print_intent() != {"FINISHED"}:
            raise AssertionError(settings.ai_message)
        wait_for_stage(settings, operators, "AI_NEEDS_INPUT")
        if len(PrintIntentHandler.request_bodies) != 1:
            raise AssertionError("第一轮请求次数不正确")
        if len(bpy.context.scene.objects) != object_count:
            raise AssertionError("缺失测量阶段修改了场景")

        settings.ai_answers = (
            "板 80×40×3 mm，圆角 2；设备孔中心 (20,20)、横向孔距 20、孔径 3.2；"
            "支架孔中心 (40,20)、纵向孔距 20、孔径 4.2"
        )
        if bpy.ops.bsa.prepare_print_intent() != {"FINISHED"}:
            raise AssertionError("第二轮数据准备失败")
        if len(PrintIntentHandler.request_bodies) != 1:
            raise AssertionError("第二轮确认前发生了网络请求")
        if bpy.ops.bsa.start_print_intent() != {"FINISHED"}:
            raise AssertionError(settings.ai_message)
        wait_for_stage(settings, operators, "REVIEW")
        if len(PrintIntentHandler.request_bodies) != 2:
            raise AssertionError("第二轮请求次数不正确")
        if len(bpy.context.scene.objects) != object_count:
            raise AssertionError("AI 候选阶段修改了场景")
        if settings.review_source != "ai" or settings.plate_id != "adapter-live-001":
            raise AssertionError("候选没有转换成可编辑参数")

        for body in PrintIntentHandler.request_bodies:
            serialized = json.dumps(body, ensure_ascii=False)
            if "scene_context" in serialized or "api_key" in serialized:
                raise AssertionError("零件请求包含禁止字段")
            if body["response_format"]["type"] != "json_schema":
                raise AssertionError("没有发送严格零件候选 Schema")
        if any(PrintIntentHandler.authorizations):
            raise AssertionError("无认证本机服务不应收到 Authorization")

        if bpy.ops.bsa.confirm_adapter_plate() != {"FINISHED"}:
            raise AssertionError(settings.result_detail)
        if settings.stage != "SUCCESS":
            raise AssertionError("候选确认后没有完成事务创建")

        port_module = importlib.import_module(package + ".blender_adapter.adapter_plate_port")
        port = port_module.BlenderAdapterPlatePort(bpy.context.scene)
        before_update = port.read_plate_design("adapter-live-001")
        before_object_count = len(bpy.context.scene.objects)
        if bpy.ops.bsa.open_adapter_plate_update() != {"FINISHED"}:
            raise AssertionError("AI 创建后无法进入修改流程")
        settings.modify_instruction = "板宽增加 10 mm，全部孔位保持不变"
        if bpy.ops.bsa.prepare_print_intent() != {"FINISHED"}:
            raise AssertionError("修改请求准备失败")
        if len(PrintIntentHandler.request_bodies) != 2:
            raise AssertionError("修改发送确认前发生了网络请求")
        if bpy.ops.bsa.start_print_intent() != {"FINISHED"}:
            raise AssertionError(settings.ai_message)
        wait_for_stage(settings, operators, "UPDATE_REVIEW")
        if len(PrintIntentHandler.request_bodies) != 3:
            raise AssertionError("修改请求次数不正确")
        if len(bpy.context.scene.objects) != before_object_count:
            raise AssertionError("修改候选确认前改变了场景")
        modification_body = PrintIntentHandler.request_bodies[-1]
        user_payload = json.loads(modification_body["messages"][1]["content"])
        if user_payload["current_design"]["plate_id"] != "adapter-live-001":
            raise AssertionError("修改请求没有发送当前受管设计")
        if "scene_context" in json.dumps(user_payload, ensure_ascii=False):
            raise AssertionError("修改请求错误发送了场景上下文")
        if bpy.ops.bsa.confirm_adapter_plate_update() != {"FINISHED"}:
            raise AssertionError(settings.error_message)
        after_update = port.read_plate_design("adapter-live-001")
        if after_update.size_mm != (90.0, 40.0, 3.0):
            raise AssertionError("AI 参数补丁没有更新真实网格")
        before_holes = {
            hole.hole_id: (
                hole.center_mm[0] + before_update.origin_offset_mm[0],
                hole.center_mm[1] + before_update.origin_offset_mm[1],
            )
            for hole in before_update.holes
        }
        after_holes = {
            hole.hole_id: (
                hole.center_mm[0] + after_update.origin_offset_mm[0],
                hole.center_mm[1] + after_update.origin_offset_mm[1],
            )
            for hole in after_update.holes
        }
        if before_holes != after_holes:
            raise AssertionError("AI 参数补丁改变了孔的世界位置")
        print(
            "BSA_PRINT_INTENT_PROVIDER_RESULT="
            + json.dumps(
                {
                    "blender_version": bpy.app.version_string,
                    "request_count": len(PrintIntentHandler.request_bodies),
                    "send_review_required": True,
                    "missing_measurement_loop": True,
                    "candidate_was_read_only": True,
                    "execution_status": "COMMITTED",
                    "output_format": "json_schema",
                    "parameter_patch_updated_mesh": True,
                    "update_world_holes_preserved": True,
                },
                ensure_ascii=True,
            )
        )
    finally:
        if extension is not None:
            extension.unregister()
        elif INSTALLED:
            addon_utils.disable(
                "bl_ext.user_default.blender_scene_assistant",
                default_set=False,
            )
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()

