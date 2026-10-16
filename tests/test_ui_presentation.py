"""简洁界面的阶段、恢复指引、中文换行和头像尺寸回归。"""

from __future__ import annotations

import unittest

from bsa.application.assistant_state import AssistantStatus
from bsa.application.ui_presentation import (
    AVATAR_HIT_RADIUS,
    AVATAR_SIZE_PX,
    POPUP_WIDTH_PX,
    display_width,
    phase_for,
    planning_config_issue,
    provider_error_message,
    text_columns,
    wrap_display_text,
)
from bsa.planner.openai_compatible import ProviderError, ProviderErrorCode


class CompactPresentationTests(unittest.TestCase):
    def test_avatar_keeps_existing_visual_and_hit_size(self) -> None:
        self.assertEqual(AVATAR_SIZE_PX, 92.0)
        self.assertEqual(AVATAR_HIT_RADIUS, 42.0)
        self.assertLessEqual(POPUP_WIDTH_PX, 440)

    def test_phases_do_not_claim_execution_before_confirmation(self) -> None:
        self.assertEqual(phase_for(AssistantStatus.IDLE).step, 1)
        self.assertEqual(phase_for(AssistantStatus.AI_REVIEW).step, 1)
        self.assertEqual(phase_for(AssistantStatus.PLANNING).step, 1)
        self.assertEqual(phase_for(AssistantStatus.PLAN_READY).step, 2)
        self.assertEqual(phase_for(AssistantStatus.WORKING).step, 3)
        self.assertEqual(phase_for(AssistantStatus.SUCCESS).step, 3)
        for status in AssistantStatus:
            self.assertTrue(phase_for(status).title)

    def test_chinese_and_ascii_wrap_without_losing_content(self) -> None:
        text = "移动 Lamp 到 Desk 顶面右侧，表面间隙 0.02 米"
        lines = wrap_display_text(text, columns=20)
        self.assertEqual("".join(lines), text)
        self.assertTrue(all(display_width(line) <= 20 for line in lines))
        self.assertEqual(display_width("中A"), 3)
        self.assertEqual(display_width("e\u0301"), 1)

    def test_wrap_retains_explicit_lines_and_long_identifiers(self) -> None:
        lines = wrap_display_text("实际执行动作：\n对象 abcdefghijklmnopqrstuvwxyz", columns=18)
        self.assertEqual(lines[0], "实际执行动作：")
        self.assertEqual("".join(lines[1:]), "对象 abcdefghijklmnopqrstuvwxyz")

    def test_narrow_and_scaled_layouts_use_fewer_columns(self) -> None:
        self.assertLess(text_columns(260), text_columns(440))
        self.assertLess(text_columns(440, ui_scale=1.5), text_columns(440))
        self.assertGreaterEqual(text_columns(100), 12)

    def test_missing_model_has_specific_recovery_and_no_network(self) -> None:
        issue = planning_config_issue("http://127.0.0.1:1234/v1", "", 15, "json_schema")
        self.assertIn("模型", issue)
        self.assertIn("设置", issue)
        self.assertIsNone(planning_config_issue(
            "http://127.0.0.1:1234/v1", "qwen", 15, "json_schema"
        ))

    def test_invalid_remote_http_is_not_made_usable_by_ui(self) -> None:
        issue = planning_config_issue("http://example.com/v1", "model", 15, "json_object")
        self.assertIn("HTTPS", issue)

    def test_invalid_provider_response_keeps_operation_specific_detail(self) -> None:
        error = ProviderError(ProviderErrorCode.INVALID_RESPONSE, "模型响应缺少 choices")
        self.assertEqual(provider_error_message(error), "模型响应缺少 choices")
        timeout = ProviderError(ProviderErrorCode.TIMEOUT, "内部超时详情")
        self.assertEqual(provider_error_message(timeout), "连接模型服务超时")


if __name__ == "__main__":
    unittest.main()
