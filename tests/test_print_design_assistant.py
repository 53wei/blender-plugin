"""3D 打印需求 AI 到本地转接板表单的应用层测试。"""

from __future__ import annotations

import unittest

from bsa.application.print_design_assistant import (
    build_print_intent_request,
    describe_missing_measurements,
    print_request_preview,
    form_from_design_candidate,
)
from bsa.domain.errors import DomainError, ErrorCode
from bsa.planner.print_intent_candidate import PrintIntentCandidate
from tests.test_print_intent_candidate import design_payload


class PrintDesignAssistantTests(unittest.TestCase):
    def test_initial_request_contains_only_user_intent(self) -> None:
        request = build_print_intent_request("做一块连接设备和支架的转接板")
        self.assertEqual(request.instruction, "做一块连接设备和支架的转接板")
        self.assertEqual(request.requested_measurements, ())
        self.assertEqual(request.measurement_answers, "")
        preview = print_request_preview(request)
        self.assertIn("用户需求", preview)
        self.assertIn("不发送 Blender 场景、网格、图片", preview)
        self.assertNotIn("80", preview)

    def test_follow_up_request_keeps_questions_and_user_answer(self) -> None:
        needs = PrintIntentCandidate.from_dict(
            {
                "schema_version": "0.1",
                "status": "needs_input",
                "part_family": "adapter_plate",
                "missing_measurements": [
                    {
                        "measurement_id": "plate_width",
                        "measurement_type": "outer_width",
                        "target_id": "adapter_plate",
                        "label": "可用板宽",
                        "reason": "决定外形是否放得下安装孔",
                        "unit": "mm",
                    }
                ],
                "assumptions": [],
                "user_summary": "需要补充板宽",
            }
        )
        request = build_print_intent_request(
            "做一块连接设备和支架的转接板",
            previous_candidate=needs,
            measurement_answers="可用宽度是 80 mm",
        )
        self.assertEqual(len(request.requested_measurements), 1)
        self.assertEqual(request.measurement_answers, "可用宽度是 80 mm")
        self.assertIn("可用板宽", print_request_preview(request))
        self.assertIn("80 mm", print_request_preview(request))
        self.assertIn("为什么要量", describe_missing_measurements(needs))

    def test_four_hole_candidate_becomes_editable_form(self) -> None:
        candidate = PrintIntentCandidate.from_dict(design_payload())
        form = form_from_design_candidate(candidate)
        self.assertEqual(form.plate_id, "adapter-demo")
        self.assertEqual((form.width_mm, form.depth_mm, form.thickness_mm), (80, 40, 3))
        self.assertEqual((form.device_center_x_mm, form.device_center_y_mm), (20, 20))
        self.assertEqual(form.device_spacing_mm, 20)
        self.assertEqual(form.device_hole_diameter_mm, 3.2)
        self.assertEqual((form.support_center_x_mm, form.support_center_y_mm), (40, 20))
        self.assertEqual(form.support_spacing_mm, 20)
        self.assertEqual(form.support_hole_diameter_mm, 4.2)

    def test_non_axis_aligned_candidate_is_explicitly_unsupported(self) -> None:
        payload = design_payload()
        payload["design"]["mounting_patterns"][0]["holes"][1]["offset_y_mm"] = 1.0
        candidate = PrintIntentCandidate.from_dict(payload)
        with self.assertRaises(DomainError) as raised:
            form_from_design_candidate(candidate)
        self.assertEqual(raised.exception.code, ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY)
        self.assertIn("沿 X 轴", raised.exception.message)

    def test_missing_answer_is_rejected_before_network(self) -> None:
        needs = PrintIntentCandidate.from_dict(
            {
                "schema_version": "0.1",
                "status": "needs_input",
                "part_family": "adapter_plate",
                "missing_measurements": [
                    {
                        "measurement_id": "width",
                        "measurement_type": "outer_width",
                        "target_id": "plate",
                        "label": "板宽",
                        "reason": "确定外形",
                        "unit": "mm",
                    }
                ],
                "assumptions": [],
                "user_summary": "需要板宽",
            }
        )
        with self.assertRaises(ValueError):
            build_print_intent_request("做转接板", previous_candidate=needs)


if __name__ == "__main__":
    unittest.main()

