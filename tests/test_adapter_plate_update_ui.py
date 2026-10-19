"""转接板修改差异预览和严格更新计划测试。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from bsa.application.adapter_plate_ui import (
    build_adapter_plate_update_plan,
    review_adapter_plate_update,
)
from bsa.core.adapter_plate import design_adapter_plate, resize_adapter_plate
from bsa.domain.adapter_plate import AdapterPlateResizePatch
from bsa.domain.errors import DomainError, ErrorCode
from tests.test_adapter_plate import make_plate


def revision():
    return resize_adapter_plate(
        make_plate(),
        AdapterPlateResizePatch(
            new_width_mm=90.0,
            new_depth_mm=None,
            fixed_x_edge="right",
            fixed_y_edge="front",
            preserve_pattern_ids=("device", "support"),
        ),
    )


class AdapterPlateUpdatePresentationTests(unittest.TestCase):
    def test_review_shows_exact_change_and_preserved_world_holes(self) -> None:
        before = design_adapter_plate(make_plate())
        current = revision()
        review = review_adapter_plate_update(
            before,
            current.design,
            user_summary="板宽增加 10 mm，孔位保持不变",
        )
        self.assertIn("80 → 90 mm", review.summary)
        self.assertIn("板深保持 40 mm", review.details)
        self.assertIn("4 个孔的世界位置和孔径保持不变", review.details)
        self.assertIn("确认前场景尚未修改", review.notice)
        plan = build_adapter_plate_update_plan(review, plan_id="ui-update-001")
        self.assertEqual(plan.action_type, "update_adapter_plate_mesh")
        self.assertEqual(plan.before_design, before)
        self.assertEqual(plan.design, current.design)
        self.assertTrue(plan.requires_confirmation)

    def test_tampered_review_cannot_become_update_plan(self) -> None:
        before = design_adapter_plate(make_plate())
        current = revision()
        review = review_adapter_plate_update(
            before,
            current.design,
            user_summary="修改板宽",
        )
        with self.assertRaises(DomainError) as raised:
            build_adapter_plate_update_plan(
                replace(review, summary="伪造摘要"),
                plan_id="ui-update-bad",
            )
        self.assertEqual(raised.exception.code, ErrorCode.PLAN_SCHEMA_INVALID)


if __name__ == "__main__":
    unittest.main()
