"""OpenAI-compatible Provider 的安全连接测试客户端。"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit, urlunsplit


MAX_RESPONSE_BYTES = 1024 * 1024
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ProviderErrorCode(StrEnum):
    """Provider 基础设施的稳定失败类型。"""

    INVALID_CONFIG = "INVALID_CONFIG"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    SERVER_ERROR = "SERVER_ERROR"
    ONLINE_ACCESS_DISABLED = "ONLINE_ACCESS_DISABLED"
    CANCELED = "CANCELED"
    WORKER_FAILED = "WORKER_FAILED"
    OUTPUT_INVALID = "PROVIDER_OUTPUT_INVALID"


@dataclass(frozen=True)
class ProviderError(Exception):
    """不会携带请求头、响应正文或密钥的安全错误。"""

    code: ProviderErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class ProviderConnectionConfig:
    """连接测试所需的非秘密配置。"""

    api_base: str
    model: str
    timeout_seconds: int
    output_format: str = "json_object"

    def validated(self) -> ProviderConnectionConfig:
        """返回规范化配置，并关闭所有可能泄密的 URL 形式。"""

        raw_url = self.api_base.strip()
        if not raw_url or len(raw_url) > 2048 or any(ord(char) < 32 for char in raw_url):
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "API 地址无效")
        try:
            parsed = urlsplit(raw_url)
            _ = parsed.port
        except ValueError as error:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "API 地址端口无效") from error
        host = (parsed.hostname or "").lower()
        if not host or parsed.username is not None or parsed.password is not None:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "API 地址不能包含账户信息")
        if parsed.query or parsed.fragment:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "API 地址不能包含查询参数或片段")
        if parsed.scheme not in {"http", "https"}:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "API 地址必须使用 HTTP 或 HTTPS")
        if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "远程 API 必须使用 HTTPS")
        if not 1 <= int(self.timeout_seconds) <= 60:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "超时时间必须在 1 到 60 秒之间")
        model = self.model.strip()
        if self.output_format not in {"json_object", "json_schema"}:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "不支持的模型输出格式")
        if len(model) > 200 or any(ord(char) < 32 for char in model):
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "模型名称无效")
        path = parsed.path.rstrip("/")
        normalized = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        return ProviderConnectionConfig(normalized, model, int(self.timeout_seconds), self.output_format)

    def validated_for_planning(self) -> ProviderConnectionConfig:
        """规划调用必须显式选择模型。"""

        checked = self.validated()
        if not checked.model:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "AI 规划需要模型名称")
        return checked


@dataclass(frozen=True)
class ConnectionTestResult:
    """连接测试的无秘密结构化结果。"""

    ok: bool
    endpoint_host: str
    models: tuple[str, ...]
    model_available: bool | None
    latency_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "endpoint_host": self.endpoint_host,
            "models": list(self.models),
            "model_available": self.model_available,
            "latency_ms": self.latency_ms,
        }


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """拒绝重定向，避免把 Authorization 发送到意外主机。"""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class OpenAICompatibleConnectionClient:
    """只访问 `/models` 的 OpenAI-compatible 连接测试。"""

    def __init__(self, *, opener: Any | None = None) -> None:
        self._opener = opener or urllib.request.build_opener(_NoRedirectHandler())

    def test_connection(
        self,
        config: ProviderConnectionConfig,
        api_key: str,
    ) -> ConnectionTestResult:
        """验证认证和基本响应结构，不发送场景或用户指令。"""

        checked = config.validated()
        host = urlsplit(checked.api_base).hostname or ""
        key = api_key.strip()
        if not key and host not in _LOOPBACK_HOSTS:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "远程服务需要 API Key")
        headers = {"Accept": "application/json", "User-Agent": "ScenePilot/0.6"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request = urllib.request.Request(
            f"{checked.api_base}/models",
            headers=headers,
            method="GET",
        )
        started = time.perf_counter()
        try:
            with self._opener.open(request, timeout=checked.timeout_seconds) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                code = ProviderErrorCode.AUTHENTICATION_FAILED
                message = "API Key 无效或没有访问权限"
            elif error.code == 429:
                code = ProviderErrorCode.RATE_LIMITED
                message = "服务请求过于频繁或额度受限"
            elif error.code >= 500:
                code = ProviderErrorCode.SERVER_ERROR
                message = "模型服务暂时不可用"
            else:
                code = ProviderErrorCode.INVALID_RESPONSE
                message = f"模型服务返回 HTTP {error.code}"
            raise ProviderError(code, message, {"http_status": error.code}) from error
        except (socket.timeout, TimeoutError) as error:
            raise ProviderError(ProviderErrorCode.TIMEOUT, "连接模型服务超时") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, (socket.timeout, TimeoutError)):
                raise ProviderError(ProviderErrorCode.TIMEOUT, "连接模型服务超时") from error
            raise ProviderError(ProviderErrorCode.CONNECTION_FAILED, "无法连接模型服务") from error
        except OSError as error:
            raise ProviderError(ProviderErrorCode.CONNECTION_FAILED, "无法连接模型服务") from error
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "模型列表响应过大")
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "模型列表不是有效 JSON") from error
        if not isinstance(decoded, dict) or not isinstance(decoded.get("data"), list):
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "模型列表结构不兼容")
        models = tuple(
            item["id"]
            for item in decoded["data"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        )
        if len(models) != len(decoded["data"]):
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "模型列表包含无效条目")
        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        return ConnectionTestResult(
            ok=True,
            endpoint_host=host,
            models=models,
            model_available=(checked.model in models) if checked.model else None,
            latency_ms=latency_ms,
        )
