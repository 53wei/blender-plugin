"""OpenAI-compatible 连接测试子进程入口；不得导入 bpy。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


MAX_INPUT_BYTES = 64 * 1024

# 以脚本运行时只把扩展根目录加入搜索路径，不继承 Blender 运行状态。
EXTENSION_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(EXTENSION_ROOT))

from bsa.planner.openai_compatible import (  # noqa: E402
    OpenAICompatibleConnectionClient,
    ProviderConnectionConfig,
    ProviderError,
    ProviderErrorCode,
)
from bsa.planner.llm.openai_chat import OpenAICompatiblePlannerClient  # noqa: E402
from bsa.planner.llm.print_intent_chat import (  # noqa: E402
    OpenAICompatiblePrintIntentClient,
)
from bsa.planner.print_intent_provider import PrintIntentRequest  # noqa: E402
from bsa.planner.provider import PlannerRequest, PlannerResponse  # noqa: E402


def _write(payload: dict[str, Any]) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _response_payload(response: PlannerResponse) -> dict[str, Any]:
    return {
        "plan_payload": response.plan_payload,
        "usage": {
            "provider": response.usage.provider,
            "model": response.usage.model,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "estimated_cost": response.usage.estimated_cost,
            "latency_ms": response.usage.latency_ms,
        },
        "request_id": response.request_id,
        "request_count": response.request_count,
        "repair_count": response.repair_count,
    }


def main() -> int:
    """读取标准输入中的短生命周期凭据并返回无秘密结果。"""

    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "Provider 配置过大")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "Provider 配置结构无效")
        config = ProviderConnectionConfig(
            api_base=str(payload.get("api_base", "")),
            model=str(payload.get("model", "")),
            timeout_seconds=int(payload.get("timeout_seconds", 0)),
            output_format=str(payload.get("output_format", "json_object")),
        )
        api_key = payload.get("api_key", "")
        if not isinstance(api_key, str):
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "API Key 类型无效")
        operation = payload.get("operation", "connection")
        if operation == "connection":
            result = OpenAICompatibleConnectionClient().test_connection(config, api_key)
            result_payload = result.to_dict()
        elif operation == "plan":
            request_payload = payload.get("request")
            if not isinstance(request_payload, dict):
                raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "规划请求结构无效")
            scene_context = request_payload.get("scene_context")
            action_schema = request_payload.get("action_schema")
            if not isinstance(scene_context, dict) or not isinstance(action_schema, dict):
                raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "规划上下文结构无效")
            planner_request = PlannerRequest(
                instruction=str(request_payload.get("instruction", "")),
                scene_context=scene_context,
                action_schema=action_schema,
            )
            response = OpenAICompatiblePlannerClient().plan(config, api_key, planner_request)
            result_payload = _response_payload(response)
        elif operation == "print_intent":
            request_payload = payload.get("request")
            if not isinstance(request_payload, dict):
                raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "零件需求请求结构无效")
            requested = request_payload.get("requested_measurements", [])
            if not isinstance(requested, list) or not all(
                isinstance(item, dict) for item in requested
            ):
                raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "测量问题结构无效")
            print_request = PrintIntentRequest(
                instruction=str(request_payload.get("instruction", "")),
                requested_measurements=tuple(requested),
                measurement_answers=str(request_payload.get("measurement_answers", "")),
            )
            response = OpenAICompatiblePrintIntentClient().plan(
                config,
                api_key,
                print_request,
            )
            result_payload = _response_payload(response)
        else:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "未知 Provider 操作")
        _write({"ok": True, "result": result_payload, "error": {}})
        return 0
    except ProviderError as error:
        _write({"ok": False, "result": {}, "error": error.to_dict()})
        return 0
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        error = ProviderError(ProviderErrorCode.INVALID_CONFIG, "Provider 配置无效")
        _write({"ok": False, "result": {}, "error": error.to_dict()})
        return 0
    except Exception:
        error = ProviderError(ProviderErrorCode.WORKER_FAILED, "Provider 工作进程发生内部错误")
        _write({"ok": False, "result": {}, "error": error.to_dict()})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
