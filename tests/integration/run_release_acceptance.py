"""使用已安装的扩展完成 0.3.0 连续指令验收。"""

from __future__ import annotations

import json
from pathlib import Path

import bpy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIRECTORY = REPOSITORY_ROOT / "docs" / "images"
RESULT_PATH = REPOSITORY_ROOT / "benchmarks" / "results" / "release_acceptance.json"


def render(path: Path) -> None:
    """渲染当前场景作为可视化验收证据。"""

    scene = bpy.context.scene
    scene.render.filepath = str(path)
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)


def main() -> int:
    """验证预览只读、确认执行、中文结果和结构化校验。"""

    if not hasattr(bpy.types.Scene, "bsa_settings"):
        raise AssertionError("已安装扩展未启用")
    if "Lamp" not in bpy.data.objects or "Desk" not in bpy.data.objects:
        raise AssertionError("演示场景缺少 Lamp 或 Desk")

    IMAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    before_image = IMAGE_DIRECTORY / "acceptance_0_3_0_before.png"
    after_image = IMAGE_DIRECTORY / "acceptance_0_3_0_after.png"

    lamp = bpy.data.objects["Lamp"]
    desk = bpy.data.objects["Desk"]
    before_location = tuple(lamp.matrix_world.translation)
    desk_matrix_before = tuple(value for row in desk.matrix_world for value in row)
    render(before_image)

    settings = bpy.context.scene.bsa_settings
    settings.instruction = "把 Lamp 放到 Desk 右侧，并锁定 Desk"

    preview_status = bpy.ops.bsa.preview_instruction()
    preview_location = tuple(lamp.matrix_world.translation)
    if preview_status != {"FINISHED"} or not settings.plan_json:
        raise AssertionError("生成预览失败")
    if preview_location != before_location:
        raise AssertionError("预览阶段修改了 Lamp")
    preview_text = settings.preview_text

    confirm_status = bpy.ops.bsa.confirm_plan()
    place_result = json.loads(settings.result_json)
    place_location = tuple(lamp.matrix_world.translation)
    if confirm_status != {"FINISHED"}:
        raise AssertionError("确认执行失败")
    if place_result["status"] != "COMMITTED" or not place_result["verification"]["passed"]:
        raise AssertionError(f"摆放结果验证未通过: {place_result}")
    if not desk.hide_select:
        raise AssertionError("摆放指令没有锁定 Desk")
    if not settings.result_text.startswith("成功"):
        raise AssertionError("用户结果不是明确的中文成功信息")
    if settings.plan_json:
        raise AssertionError("成功后旧计划仍可重复执行")

    settings.instruction = "Lamp 向左移动 20 厘米"
    move_preview_status = bpy.ops.bsa.preview_instruction()
    move_preview_location = tuple(lamp.matrix_world.translation)
    move_preview_text = settings.preview_text
    if move_preview_status != {"FINISHED"} or move_preview_location != place_location:
        raise AssertionError("移动预览失败或提前修改了 Lamp")
    if bpy.ops.bsa.confirm_plan() != {"FINISHED"}:
        raise AssertionError("移动指令确认失败")
    move_result = json.loads(settings.result_json)
    after_location = tuple(lamp.matrix_world.translation)
    if move_result["status"] != "COMMITTED" or not move_result["verification"]["passed"]:
        raise AssertionError(f"移动结果验证未通过: {move_result}")
    if abs((after_location[0] - place_location[0]) + 0.2) > 1e-4:
        raise AssertionError("Lamp 没有沿世界坐标负 X 移动 20 厘米")

    settings.instruction = "解除锁定 Desk"
    unlock_preview_status = bpy.ops.bsa.preview_instruction()
    unlock_preview_text = settings.preview_text
    if unlock_preview_status != {"FINISHED"} or not desk.hide_select:
        raise AssertionError("解除锁定预览修改了场景或生成失败")
    if bpy.ops.bsa.confirm_plan() != {"FINISHED"}:
        raise AssertionError("解除锁定确认失败")
    unlock_result = json.loads(settings.result_json)
    if unlock_result["status"] != "COMMITTED" or desk.hide_select:
        raise AssertionError("Desk 没有成功解除锁定")

    desk_matrix_after = tuple(value for row in desk.matrix_world for value in row)
    if desk_matrix_after != desk_matrix_before:
        raise AssertionError("连续操作意外改变了 Desk 变换")

    render(after_image)
    results = (place_result, move_result, unlock_result)
    report = {
        "blender_version": bpy.app.version_string,
        "extension_version": "0.3.0",
        "source": "Lamp",
        "target": "Desk",
        "region": "right",
        "preview_was_read_only": (
            preview_location == before_location
            and move_preview_location == place_location
            and unlock_preview_status == {"FINISHED"}
        ),
        "preview_texts": [preview_text, move_preview_text, unlock_preview_text],
        "execution_statuses": [result["status"] for result in results],
        "verification_passed": all(
            result["verification"]["passed"] for result in results
        ),
        "passed_checks": sum(
            check["passed"]
            for result in results
            for check in result["verification"]["checks"]
        ),
        "total_checks": sum(
            len(result["verification"]["checks"]) for result in results
        ),
        "human_result": settings.result_text,
        "before_location": list(before_location),
        "placed_location": list(place_location),
        "after_location": list(after_location),
        "desk_transform_preserved": desk_matrix_after == desk_matrix_before,
        "desk_unlocked_at_end": not desk.hide_select,
        "before_image": str(before_image),
        "after_image": str(after_image),
    }
    RESULT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("BSA_RELEASE_ACCEPTANCE=" + json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
