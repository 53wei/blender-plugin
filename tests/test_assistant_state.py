"""场景领航员界面状态机测试。"""

from __future__ import annotations

import unittest

from bsa.application.assistant_state import (
    AssistantEvent,
    AssistantStatus,
    next_status,
    presentation_for,
)


class AssistantStateTests(unittest.TestCase):
    """状态变化必须可预测，不能把未执行计划显示成成功。"""

    def test_happy_path_requires_plan_and_execution(self) -> None:
        status = AssistantStatus.IDLE
        status = next_status(status, AssistantEvent.PREVIEW_READY)
        self.assertEqual(status, AssistantStatus.PLAN_READY)
        status = next_status(status, AssistantEvent.EXECUTION_STARTED)
        self.assertEqual(status, AssistantStatus.WORKING)
        status = next_status(status, AssistantEvent.EXECUTION_SUCCEEDED)
        self.assertEqual(status, AssistantStatus.SUCCESS)

    def test_ai_path_requires_data_review_then_planning_then_preview(self) -> None:
        status = next_status(AssistantStatus.IDLE, AssistantEvent.AI_REVIEW_READY)
        self.assertEqual(status, AssistantStatus.AI_REVIEW)
        status = next_status(status, AssistantEvent.AI_PLANNING_STARTED)
        self.assertEqual(status, AssistantStatus.PLANNING)
        status = next_status(status, AssistantEvent.PREVIEW_READY)
        self.assertEqual(status, AssistantStatus.PLAN_READY)

    def test_failure_and_clear_are_available_from_active_states(self) -> None:
        self.assertEqual(
            next_status(AssistantStatus.WORKING, AssistantEvent.FAILED),
            AssistantStatus.ERROR,
        )
        self.assertEqual(
            next_status(AssistantStatus.ERROR, AssistantEvent.CLEARED),
            AssistantStatus.IDLE,
        )

    def test_success_without_execution_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            next_status(AssistantStatus.IDLE, AssistantEvent.EXECUTION_SUCCEEDED)

    def test_every_status_has_chinese_presentation(self) -> None:
        for status in AssistantStatus:
            presentation = presentation_for(status)
            self.assertTrue(presentation.label)
            self.assertTrue(presentation.detail)
            self.assertEqual(len(presentation.color), 3)


if __name__ == "__main__":
    unittest.main()
