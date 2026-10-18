"""3D 打印零件 AI 候选协议的关闭字段与本地转换测试。"""

from __future__ import annotations

import math
import unittest

from bsa.domain.errors import DomainError, ErrorCode
from bsa.planner.print_intent_candidate import (
    PrintIntentCandidate,
    build_adapter_plate_design,
    build_adapter_plate_revision,
    print_intent_json_schema,
)
from tests.test_adapter_plate import make_plate, world_holes


def design_payload() -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "status": "design_candidate",
        "part_family": "adapter_plate",
        "design": {
            "plate_id": "adapter-demo",
            "width_mm": 80.0,
            "depth_mm": 40.0,
            "thickness_mm": 3.0,
            "corner_radius_mm": 2.0,
            "mounting_patterns": [
                {
                    "pattern_id": "device",
                    "origin_x_mm": 20.0,
                    "origin_y_mm": 20.0,
                    "holes": [
                        {
                            "hole_id": "device-left",
                            "offset_x_mm": -10.0,
                            "offset_y_mm": 0.0,
                            "diameter_mm": 3.2,
                        },
                        {
                            "hole_id": "device-right",
                            "offset_x_mm": 10.0,
                            "offset_y_mm": 0.0,
                            "diameter_mm": 3.2,
                        },
                    ],
                },
                {
                    "pattern_id": "support",
                    "origin_x_mm": 40.0,
                    "origin_y_mm": 20.0,
                    "holes": [
                        {
                            "hole_id": "support-front",
                            "offset_x_mm": 0.0,
                            "offset_y_mm": -10.0,
                            "diameter_mm": 4.2,
                        },
                        {
                            "hole_id": "support-back",
                            "offset_x_mm": 0.0,
                            "offset_y_mm": 10.0,
                            "diameter_mm": 4.2,
                        },
                    ],
                },
            ],
        },
        "assumptions": ["所有尺寸均由用户测量"],
        "user_summary": "生成 80×40×3 毫米转接板",
    }


def patch_payload() -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "status": "parameter_patch",
        "part_family": "adapter_plate",
        "target_plate_id": "adapter-demo",
        "patch": {
            "new_width_mm": 90.0,
            "fixed_x_edge": "left",
            "fixed_y_edge": "front",
            "preserve_pattern_ids": ["device", "support"],
        },
        "preserve_relations": ["hole_world_centers"],
        "assumptions": [],
        "user_summary": "板加长 10 毫米，所有孔位保持不变",
    }


class PrintIntentCandidateTests(unittest.TestCase):
    def test_schema_has_exactly_three_closed_status_branches(self) -> None:
        schema = print_intent_json_schema()
        branches = schema["oneOf"]
        self.assertEqual(
            {branch["properties"]["status"]["const"] for branch in branches},
            {"needs_input", "design_candidate", "parameter_patch"},
        )
        self.assertTrue(all(branch["additionalProperties"] is False for branch in branches))
        encoded = str(schema)
        for forbidden in ("python", "api_key", "requires_confirmation", "source"):
            self.assertNotIn(forbidden, encoded)

    def test_needs_input_roundtrip_is_typed_and_closed(self) -> None:
        payload = {
            "schema_version": "0.1",
            "status": "needs_input",
            "part_family": "adapter_plate",
            "missing_measurements": [
                {
                    "measurement_id": "device-hole-spacing",
                    "measurement_type": "hole_center_x",
                    "target_id": "device",
                    "label": "设备两孔中心距",
                    "reason": "决定设备孔组位置",
                    "unit": "mm",
                }
            ],
            "assumptions": [],
            "user_summary": "还需要设备孔距",
        }
        candidate = PrintIntentCandidate.from_dict(payload)
        self.assertEqual(candidate.status, "needs_input")
        self.assertEqual(candidate.missing_measurements[0].unit, "mm")
        self.assertEqual(candidate.to_dict(), payload)

    def test_design_candidate_becomes_validated_typed_design(self) -> None:
        candidate = PrintIntentCandidate.from_dict(design_payload())
        design = build_adapter_plate_design(candidate)
        self.assertEqual(design.size_mm, (80.0, 40.0, 3.0))
        self.assertEqual(len(design.holes), 4)
        self.assertEqual(candidate.to_dict(), design_payload())

    def test_parameter_patch_preserves_hole_world_positions(self) -> None:
        candidate = PrintIntentCandidate.from_dict(patch_payload())
        before = build_adapter_plate_design(PrintIntentCandidate.from_dict(design_payload()))
        revision = build_adapter_plate_revision(candidate, make_plate())
        self.assertEqual(revision.design.size_mm[0], 90.0)
        self.assertEqual(world_holes(revision.design), world_holes(before))

    def test_unknown_fields_python_and_trusted_fields_fail_closed(self) -> None:
        payloads = []
        for key, value in (
            ("python", "bpy.ops.object.delete()"),
            ("api_key", "secret"),
            ("source", "trusted"),
            ("requires_confirmation", False),
            ("design_fingerprint", "forged"),
        ):
            payload = design_payload()
            payload[key] = value
            payloads.append(payload)
        nested = design_payload()
        nested["design"]["mesh"] = "arbitrary"  # type: ignore[index]
        payloads.append(nested)
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(DomainError) as raised:
                PrintIntentCandidate.from_dict(payload)
            self.assertEqual(raised.exception.code, ErrorCode.PLAN_SCHEMA_INVALID)

    def test_unknown_family_status_and_unbounded_numbers_are_rejected(self) -> None:
        unknown_family = design_payload()
        unknown_family["part_family"] = "arbitrary_mesh"
        unknown_status = design_payload()
        unknown_status["status"] = "execute_python"
        infinity = design_payload()
        infinity["design"]["width_mm"] = math.inf  # type: ignore[index]
        boolean_number = design_payload()
        boolean_number["design"]["width_mm"] = True  # type: ignore[index]
        for payload in (unknown_family, unknown_status, infinity, boolean_number):
            with self.subTest(payload=payload), self.assertRaises(DomainError) as raised:
                PrintIntentCandidate.from_dict(payload)
            self.assertEqual(raised.exception.code, ErrorCode.PLAN_SCHEMA_INVALID)

    def test_schema_shaped_but_geometrically_invalid_design_fails_locally(self) -> None:
        payload = design_payload()
        payload["design"]["width_mm"] = 20.0  # type: ignore[index]
        candidate = PrintIntentCandidate.from_dict(payload)
        with self.assertRaises(DomainError) as raised:
            build_adapter_plate_design(candidate)
        self.assertEqual(raised.exception.code, ErrorCode.PRINT_SPEC_INVALID)

    def test_patch_requires_dimension_and_exact_current_plate(self) -> None:
        missing_dimension = patch_payload()
        missing_dimension["patch"].pop("new_width_mm")  # type: ignore[union-attr]
        with self.assertRaises(DomainError) as raised:
            PrintIntentCandidate.from_dict(missing_dimension)
        self.assertEqual(raised.exception.code, ErrorCode.PLAN_SCHEMA_INVALID)

        wrong_target = patch_payload()
        wrong_target["target_plate_id"] = "another-plate"
        candidate = PrintIntentCandidate.from_dict(wrong_target)
        with self.assertRaises(DomainError) as raised:
            build_adapter_plate_revision(candidate, make_plate())
        self.assertEqual(raised.exception.code, ErrorCode.OBJECT_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
