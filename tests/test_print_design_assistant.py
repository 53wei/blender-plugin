"""3D 打印需求 AI 到本地转接板表单的应用层测试。"""

from __future__ import annotations

import unittest

from bsa.application.print_design_assistant import (
    build_parameter_patch_revision,
    build_print_intent_request,
    describe_missing_measurements,
    print_request_preview,
    form_from_design_candidate,
)
from bsa.core.adapter_plate import design_adapter_plate
from bsa.domain.errors import DomainError, ErrorCode
from bsa.planner.print_intent_candidate import PrintIntentCandidate
from tests.test_print_intent_candidate import design_payload
from tests.test_adapter_plate import make_plate


def world_holes(design):
    return {
        hole.hole_id: (
            hole.center_mm[0] + design.origin_offset_mm[0],
            hole.center_mm[1] + design.origin_offset_mm[1],
        )
        for hole in design.holes
    }


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

    def test_modification_request_includes_only_current_managed_design(self) -> None:
        current = design_adapter_plate(make_plate())
        request = build_print_intent_request(
            "板加长 10 mm，所有孔的位置保持不变",
            current_design=current,
        )
        self.assertEqual(request.current_design, current.to_dict())
        preview = print_request_preview(request)
        self.assertIn("当前零件：adapter-demo", preview)
        self.assertIn("80 × 40 × 3 mm", preview)
        self.assertIn("4 个贯穿孔", preview)
        self.assertIn("不发送 Blender 场景", preview)

    def test_parameter_patch_builds_cumulative_verified_revision(self) -> None:
        current = design_adapter_plate(make_plate(), origin_offset_mm=(-5.0, 0.0, 0.0))
        payload = {
            "schema_version": "0.1",
            "status": "parameter_patch",
            "part_family": "adapter_plate",
            "target_plate_id": "adapter-demo",
            "patch": {
                "new_width_mm": 90.0,
                "fixed_x_edge": "right",
                "fixed_y_edge": "front",
                "preserve_pattern_ids": ["device", "support"],
            },
            "preserve_relations": ["hole_world_centers"],
            "assumptions": [],
            "user_summary": "板宽改为 90 mm，孔位保持不变",
        }
        revision = build_parameter_patch_revision(
            PrintIntentCandidate.from_dict(payload),
            current,
        )
        self.assertEqual(revision.design.origin_offset_mm, (-15.0, 0.0, 0.0))
        self.assertEqual(world_holes(revision.design), world_holes(current))


if __name__ == "__main__":
    unittest.main()

