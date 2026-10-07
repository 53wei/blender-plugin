"""用户确认前的真实动作清单回归测试。"""

from dataclasses import replace
import unittest

from bsa.application.plan_preview import describe_plan
from bsa.domain.actions import MoveAction
from tests.support import make_place_plan, make_scene


class PlanPreviewTests(unittest.TestCase):
    def test_misleading_model_summary_cannot_hide_actual_object_and_delta(self) -> None:
        scene = make_scene()
        plan = replace(
            make_place_plan(scene),
            source="llm",
            actions=(MoveAction("move-1", "desk-id", (0.25, 0.0, 0.0)),),
            user_summary="只移动 Lamp，不动 Desk",
        )
        text = describe_plan(plan, scene.read_snapshot())
        self.assertIn("实际执行动作", text)
        self.assertIn("移动 Desk", text)
        self.assertIn("[0.25, 0, 0]", text)
        self.assertIn("模型建议", text)
        self.assertIn("保持 Desk 的变换不动", text)

    def test_placement_names_target_region_clearance_and_lock(self) -> None:
        scene = make_scene()
        text = describe_plan(make_place_plan(scene, lock_target=True), scene.read_snapshot())
        self.assertIn("Lamp", text)
        self.assertIn("Desk 的右侧", text)
        self.assertIn("间隙 0 米", text)
        self.assertIn("锁定 Desk", text)

    def test_unit_scale_changes_meter_display_without_changing_action(self) -> None:
        scene = make_scene()
        plan = replace(make_place_plan(scene), actions=(MoveAction("m", "lamp-id", (20, 0, 0)),))
        snapshot = replace(scene.read_snapshot(), unit_scale=0.01)
        text = describe_plan(plan, snapshot)
        self.assertIn("[20, 0, 0]", text)
        self.assertIn("[0.2, 0, 0] 米", text)


if __name__ == "__main__":
    unittest.main()
