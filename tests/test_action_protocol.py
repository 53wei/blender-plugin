"""Strict JSON protocol tests."""

from __future__ import annotations

import unittest

from bsa.domain.actions import ActionPlan
from bsa.domain.errors import DomainError, ErrorCode


class ActionProtocolTests(unittest.TestCase):
    def valid_payload(self) -> dict[str, object]:
        return {
            "schema_version": "0.1",
            "plan_id": "plan-1",
            "source": "test",
            "scene_fingerprint": "sha256:abc",
            "requires_confirmation": False,
            "actions": [
                {
                    "action_id": "a1",
                    "type": "place_on",
                    "object_id": "lamp-id",
                    "target_id": "desk-id",
                    "region": "right",
                    "clearance": 0.0,
                }
            ],
            "constraints": [],
            "user_summary": "Place the lamp",
        }

    def test_round_trip_is_stable(self) -> None:
        payload = self.valid_payload()
        self.assertEqual(ActionPlan.from_dict(payload).to_dict(), payload)

    def test_unknown_top_level_field_fails_closed(self) -> None:
        payload = self.valid_payload()
        payload["execute_python"] = "malicious()"
        with self.assertRaises(DomainError) as raised:
            ActionPlan.from_dict(payload)
        self.assertEqual(raised.exception.code, ErrorCode.PLAN_SCHEMA_INVALID)

    def test_unknown_action_is_rejected(self) -> None:
        payload = self.valid_payload()
        payload["actions"] = [{"action_id": "a1", "type": "run_python"}]
        with self.assertRaises(DomainError) as raised:
            ActionPlan.from_dict(payload)
        self.assertEqual(raised.exception.code, ErrorCode.ACTION_NOT_SUPPORTED)

    def test_non_finite_numbers_are_rejected(self) -> None:
        payload = self.valid_payload()
        payload["actions"][0]["clearance"] = float("nan")  # type: ignore[index]
        with self.assertRaises(DomainError) as raised:
            ActionPlan.from_dict(payload)
        self.assertEqual(raised.exception.code, ErrorCode.PLAN_SCHEMA_INVALID)


if __name__ == "__main__":
    unittest.main()
