"""BYOK 会话凭据解析与脱敏测试。"""

from __future__ import annotations

import unittest

from bsa.infra.credentials import CredentialSource, resolve_api_key


class CredentialTests(unittest.TestCase):
    def test_session_key_has_priority_without_leaking_from_repr(self) -> None:
        resolved = resolve_api_key(
            "sk-session-secret",
            {"BSA_API_KEY": "sk-bsa-env", "OPENAI_API_KEY": "sk-openai-env"},
        )
        self.assertEqual(resolved.value, "sk-session-secret")
        self.assertEqual(resolved.source, CredentialSource.SESSION)
        self.assertNotIn("sk-session-secret", repr(resolved))

    def test_environment_fallback_order_is_explicit(self) -> None:
        bsa = resolve_api_key("", {"BSA_API_KEY": "bsa-value", "OPENAI_API_KEY": "openai-value"})
        self.assertEqual(bsa.source, CredentialSource.BSA_ENV)
        self.assertEqual(bsa.value, "bsa-value")
        openai = resolve_api_key("", {"OPENAI_API_KEY": "openai-value"})
        self.assertEqual(openai.source, CredentialSource.OPENAI_ENV)

    def test_missing_key_is_reported_without_fake_value(self) -> None:
        resolved = resolve_api_key("", {})
        self.assertEqual(resolved.source, CredentialSource.NONE)
        self.assertEqual(resolved.value, "")


if __name__ == "__main__":
    unittest.main()
