"""转接板本地创建界面的纯参数映射与阶段文案。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from bsa.application.adapter_plate_ui import (
    AdapterPlateForm,
    build_adapter_plate_creation_plan,
    review_adapter_plate_form,
)
from bsa.domain.errors import DomainError, ErrorCode


def default_form() -> AdapterPlateForm:
    return AdapterPlateForm(
        plate_id="adapter-001",
        width_mm=80.0,
        depth_mm=40.0,
        thickness_mm=3.0,
        corner_radius_mm=2.0,
        device_center_x_mm=20.0,
        device_center_y_mm=20.0,
        device_spacing_mm=20.0,
        device_hole_diameter_mm=3.2,
        support_center_x_mm=40.0,
        support_center_y_mm=20.0,
        support_spacing_mm=20.0,
        support_hole_diameter_mm=4.2,
    )


class AdapterPlateUiPresentationTests(unittest.TestCase):
    def test_default_form_maps_to_two_verified_hole_patterns(self) -> None:
        review = review_adapter_plate_form(default_form())
        self.assertEqual(review.design.size_mm, (80.0, 40.0, 3.0))
        self.assertEqual(
            tuple(hole.center_mm for hole in review.design.holes),
            ((10.0, 20.0), (30.0, 20.0), (40.0, 10.0), (40.0, 30.0)),
        )
        self.assertEqual(
            tuple(hole.diameter_mm for hole in review.design.holes),
            (3.2, 3.2, 4.2, 4.2),
        )
        self.assertIn("80 × 40 × 3 mm", review.summary)
        self.assertIn("4 个贯穿孔", review.summary)
        self.assertIn("设备孔组", review.details)
        self.assertIn("支架孔组", review.details)
        self.assertIn("尚未修改", review.notice)

    def test_review_fingerprint_changes_with_every_executable_field(self) -> None:
        base = review_adapter_plate_form(default_form())
        changed = (
            replace(default_form(), plate_id="adapter-002"),
            replace(default_form(), width_mm=81.0),
            replace(default_form(), device_center_y_mm=19.0),
            replace(default_form(), support_hole_diameter_mm=4.3),
        )
        for form in changed:
            with self.subTest(form=form):
                self.assertNotEqual(
                    review_adapter_plate_form(form).fingerprint,
                    base.fingerprint,
                )

    def test_invalid_identifier_and_hole_geometry_have_recoverable_errors(self) -> None:
        cases = (
            (replace(default_form(), plate_id="转接板 1"), "零件编号"),
            (replace(default_form(), device_center_x_mm=2.0), "未完整落在板轮廓内"),
            (replace(default_form(), support_spacing_mm=0.0), "正有限数值"),
        )
        for form, message in cases:
            with self.subTest(form=form), self.assertRaises(DomainError) as raised:
                review_adapter_plate_form(form)
            self.assertEqual(raised.exception.code, ErrorCode.PRINT_SPEC_INVALID)
            self.assertIn(message, raised.exception.message)

    def test_creation_plan_is_typed_and_always_requires_confirmation(self) -> None:
        review = review_adapter_plate_form(default_form())
        plan = build_adapter_plate_creation_plan(
            review,
            plan_id="adapter-ui-001",
        )
        self.assertEqual(plan.action_type, "create_adapter_plate_mesh")
        self.assertEqual(plan.source, "adapter_plate_ui")
        self.assertTrue(plan.requires_confirmation)
        self.assertEqual(plan.plate_id, "adapter-001")
        self.assertEqual(plan.design, review.design)
        self.assertIn("4 个贯穿孔", plan.user_summary)

    def test_handcrafted_review_cannot_replace_validated_design(self) -> None:
        review = review_adapter_plate_form(default_form())
        tampered = replace(review, fingerprint="wrong")
        with self.assertRaises(DomainError) as raised:
            build_adapter_plate_creation_plan(tampered, plan_id="adapter-ui-002")
        self.assertEqual(raised.exception.code, ErrorCode.PLAN_SCHEMA_INVALID)


if __name__ == "__main__":
    unittest.main()

