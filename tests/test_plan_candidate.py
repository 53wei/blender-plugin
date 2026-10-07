"""模型候选计划的严格解析与可信字段补全测试。"""

from __future__ import annotations

import unittest

from bsa.domain.errors import DomainError, ErrorCode
from bsa.domain.actions import UnlockAction
from bsa.planner.plan_candidate import (
    PlanCandidate,
    build_action_plan,
    candidate_action_schema,
    candidate_json_schema,
)
from tests.support import make_scene


def valid_candidate() -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "actions": [
            {
                "action_id": "place-1",
                "type": "place_on",
                "object_id": "lamp-id",
                "target_id": "desk-id",
                "region": "right",
                "clearance": 0.0,
            }
        ],
        "constraints": [
            {
                "constraint_id": "preserve-1",
                "type": "preserve_transform",
                "object_id": "desk-id",
                "severity": "hard",
            }
        ],
        "user_summary": "将 Lamp 放到 Desk 右侧，保持 Desk 不动",
    }


class PlanCandidateTests(unittest.TestCase):
    def test_move_candidate_to_dict_roundtrip_uses_json_array(self) -> None:
        payload = valid_candidate()
        payload["actions"] = [{"action_id": "move-1", "type": "move", "object_id": "lamp-id", "delta": [0.2, 0, 0], "space": "world"}]
        candidate = PlanCandidate.from_dict(payload, allowed_object_ids={"desk-id", "lamp-id"})
        encoded = candidate.to_dict()
        self.assertIsInstance(encoded["actions"][0]["delta"], list)
        restored = PlanCandidate.from_dict(encoded, allowed_object_ids={"desk-id", "lamp-id"})
        self.assertEqual(restored, candidate)
        plan = build_action_plan(restored, make_scene().read_snapshot())
        self.assertIsInstance(plan.to_dict()["actions"][0]["delta"], list)

    def test_generation_schema_has_only_existing_ai_actions_and_closed_fields(self) -> None:
        schema = candidate_json_schema(["desk-id", "lamp-id"])
        branches = schema["properties"]["actions"]["items"]["anyOf"]
        self.assertEqual({item["properties"]["type"]["const"] for item in branches}, {"place_on", "move", "lock"})
        self.assertTrue(all(item["additionalProperties"] is False for item in branches))
        self.assertTrue(all(set(item["required"]) == set(item["properties"]) for item in branches))
        move = next(item for item in branches if item["properties"]["type"]["const"] == "move")
        self.assertEqual(move["properties"]["delta"]["minItems"], 3)
        self.assertEqual(move["properties"]["delta"]["maxItems"], 3)
        self.assertNotIn("scene_fingerprint", schema["properties"])
        self.assertNotIn("requires_confirmation", schema["properties"])

    def test_direct_candidate_cannot_bypass_ai_unlock_guard(self) -> None:
        candidate = PlanCandidate("0.1", (UnlockAction("unlock-1", "desk-id"),), (), "解锁")
        with self.assertRaises(DomainError) as raised:
            build_action_plan(candidate, make_scene().read_snapshot())
        self.assertEqual(raised.exception.code, ErrorCode.OBJECT_LOCKED)

    def test_model_schema_contains_exact_examples_for_every_enabled_action(self) -> None:
        schema = candidate_action_schema()
        examples = schema["action_examples"]
        self.assertEqual(
            {example["type"] for example in examples},
            {"place_on", "move", "lock"},
        )
        place_on = next(item for item in examples if item["type"] == "place_on")
        self.assertEqual(
            set(place_on),
            {"action_id", "type", "object_id", "target_id", "region", "clearance"},
        )
        self.assertEqual(
            set(schema["constraint_example"]),
            {"constraint_id", "type", "object_id", "severity"},
        )

    def test_ai_cannot_unlock_objects_even_if_json_is_otherwise_valid(self) -> None:
        payload = valid_candidate()
        payload["actions"] = [
            {"action_id": "unlock-1", "type": "unlock", "object_id": "desk-id"}
        ]
        with self.assertRaises(DomainError) as raised:
            PlanCandidate.from_dict(payload, allowed_object_ids={"desk-id", "lamp-id"})
        self.assertEqual(raised.exception.code, ErrorCode.OBJECT_LOCKED)

    def test_candidate_becomes_confirmable_llm_plan_with_local_trust_fields(self) -> None:
        snapshot = make_scene().read_snapshot()
        candidate = PlanCandidate.from_dict(
            valid_candidate(), allowed_object_ids={"desk-id", "lamp-id", "chair-id"}
        )
        plan = build_action_plan(candidate, snapshot, plan_id="trusted-plan-id")
        self.assertEqual(plan.plan_id, "trusted-plan-id")
        self.assertEqual(plan.source, "llm")
        self.assertTrue(plan.requires_confirmation)
        self.assertTrue(plan.scene_fingerprint.startswith("sha256:"))
        self.assertEqual(plan.actions[0].object_id, "lamp-id")

    def test_unknown_fields_actions_and_object_ids_fail_closed(self) -> None:
        cases = []
        unknown_top = valid_candidate()
        unknown_top["python"] = "bpy.ops.object.delete()"
        cases.append(unknown_top)
        unknown_action = valid_candidate()
        unknown_action["actions"] = [
            {"action_id": "x", "type": "python", "code": "print('unsafe')"}
        ]
        cases.append(unknown_action)
        unknown_object = valid_candidate()
        unknown_object["actions"][0]["object_id"] = "hallucinated-id"  # type: ignore[index]
        cases.append(unknown_object)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(DomainError):
                PlanCandidate.from_dict(
                    payload, allowed_object_ids={"desk-id", "lamp-id", "chair-id"}
                )

    def test_empty_plan_duplicate_ids_and_non_string_ids_are_rejected(self) -> None:
        empty = valid_candidate()
        empty["actions"] = []
        duplicate = valid_candidate()
        duplicate["actions"] = [
            {"action_id": "same", "type": "lock", "object_id": "desk-id"},
            {"action_id": "same", "type": "unlock", "object_id": "desk-id"},
        ]
        non_string = valid_candidate()
        non_string["actions"][0]["action_id"] = 7  # type: ignore[index]
        for payload in (empty, duplicate, non_string):
            with self.subTest(payload=payload), self.assertRaises(DomainError):
                PlanCandidate.from_dict(
                    payload, allowed_object_ids={"desk-id", "lamp-id", "chair-id"}
                )

    def test_unsafe_move_distance_is_rejected_before_execution(self) -> None:
        payload = valid_candidate()
        payload["actions"] = [
            {
                "action_id": "move-1",
                "type": "move",
                "object_id": "lamp-id",
                "delta": [10001.0, 0.0, 0.0],
                "space": "world",
            }
        ]
        payload["constraints"] = []
        candidate = PlanCandidate.from_dict(
            payload, allowed_object_ids={"desk-id", "lamp-id", "chair-id"}
        )
        with self.assertRaises(DomainError) as raised:
            build_action_plan(candidate, make_scene().read_snapshot())
        self.assertEqual(raised.exception.code, ErrorCode.PRECONDITION_FAILED)


if __name__ == "__main__":
    unittest.main()
