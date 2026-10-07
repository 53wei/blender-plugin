"""OpenAI-compatible 连接客户端测试。"""

from __future__ import annotations

import io
import socket
import unittest
import urllib.error

from bsa.planner.openai_compatible import (
    OpenAICompatibleConnectionClient,
    ProviderConnectionConfig,
    ProviderError,
    ProviderErrorCode,
)


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _amount: int) -> bytes:
        return self._payload


class _RecordingOpener:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.request = None
        self.timeout = None

    def open(self, request, timeout: float):
        self.request = request
        self.timeout = timeout
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class OpenAICompatibleTests(unittest.TestCase):
    def test_remote_endpoint_requires_https_and_clean_url(self) -> None:
        for url in (
            "http://api.example.com/v1",
            "https://user:pass@api.example.com/v1",
            "https://api.example.com/v1?token=bad",
            "https://api.example.com/v1#fragment",
        ):
            with self.subTest(url=url), self.assertRaises(ProviderError) as raised:
                ProviderConnectionConfig(url, "model-a", 10).validated()
            self.assertEqual(raised.exception.code, ProviderErrorCode.INVALID_CONFIG)

    def test_loopback_http_is_allowed_for_local_models(self) -> None:
        config = ProviderConnectionConfig("http://127.0.0.1:11434/v1/", "local", 5).validated()
        self.assertEqual(config.api_base, "http://127.0.0.1:11434/v1")

    def test_success_uses_bearer_key_and_reports_models(self) -> None:
        opener = _RecordingOpener(_FakeResponse(b'{"data":[{"id":"model-a"},{"id":"model-b"}]}'))
        client = OpenAICompatibleConnectionClient(opener=opener)
        result = client.test_connection(
            ProviderConnectionConfig("https://api.example.com/v1", "model-a", 7),
            "sk-super-secret",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.models, ("model-a", "model-b"))
        self.assertTrue(result.model_available)
        self.assertEqual(opener.timeout, 7)
        self.assertEqual(opener.request.full_url, "https://api.example.com/v1/models")
        self.assertEqual(opener.request.get_header("Authorization"), "Bearer sk-super-secret")
        self.assertNotIn("sk-super-secret", repr(result))

    def test_auth_rate_limit_and_server_errors_are_stable(self) -> None:
        cases = (
            (401, ProviderErrorCode.AUTHENTICATION_FAILED),
            (403, ProviderErrorCode.AUTHENTICATION_FAILED),
            (429, ProviderErrorCode.RATE_LIMITED),
            (500, ProviderErrorCode.SERVER_ERROR),
        )
        for status, expected in cases:
            error = urllib.error.HTTPError(
                "https://api.example.com/v1/models",
                status,
                "failure",
                {},
                io.BytesIO(b"ignored"),
            )
            with self.subTest(status=status), self.assertRaises(ProviderError) as raised:
                OpenAICompatibleConnectionClient(opener=_RecordingOpener(error)).test_connection(
                    ProviderConnectionConfig("https://api.example.com/v1", "", 5),
                    "secret",
                )
            self.assertEqual(raised.exception.code, expected)
            self.assertNotIn("secret", str(raised.exception))

    def test_timeout_invalid_json_and_oversize_response_fail_closed(self) -> None:
        cases = (
            (socket.timeout("late"), ProviderErrorCode.TIMEOUT),
            (_FakeResponse(b"not-json"), ProviderErrorCode.INVALID_RESPONSE),
            (_FakeResponse(b"x" * (1024 * 1024 + 1)), ProviderErrorCode.INVALID_RESPONSE),
        )
        for outcome, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(ProviderError) as raised:
                OpenAICompatibleConnectionClient(opener=_RecordingOpener(outcome)).test_connection(
                    ProviderConnectionConfig("https://api.example.com/v1", "", 5),
                    "secret",
                )
            self.assertEqual(raised.exception.code, expected)


if __name__ == "__main__":
    unittest.main()
