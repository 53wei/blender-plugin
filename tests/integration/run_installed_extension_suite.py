"""Verify the built ZIP after installation into an isolated Blender user repository."""

from __future__ import annotations

import json
from pathlib import Path

import addon_utils
import bpy

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def add_cube(name: str, location: tuple[float, float, float], scale: tuple[float, float, float]):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.context.view_layer.update()
    return obj


def main() -> int:
    addon_utils.enable(
        "bl_ext.user_default.blender_scene_assistant",
        default_set=False,
        persistent=False,
    )
    if not hasattr(bpy.types.Scene, "bsa_settings"):
        raise AssertionError("Installed extension is not enabled")
    if not hasattr(bpy.types.WindowManager, "bsa_provider_session"):
        raise AssertionError("Installed provider session is missing")
    if hasattr(bpy.types.Scene, "bsa_provider_session"):
        raise AssertionError("Installed provider credentials were attached to Scene")

    from bl_ext.user_default.blender_scene_assistant.bsa.ui.operators import (
        BSA_OT_confirm_plan,
        BSA_OT_launch_assistant,
        BSA_OT_open_assistant,
        BSA_OT_preview_instruction,
        BSA_OT_preview_plan,
        BSA_OT_start_ai_planning,
        BSA_OT_cancel_ai_planning,
        BSA_OT_discard_ai_request,
        BSA_OT_cancel_provider_connection,
        BSA_OT_test_provider_connection,
    )
    from bl_ext.user_default.blender_scene_assistant.bsa.ui.adapter_plate_operators import (
        BSA_OT_open_print_part,
    )
    from bl_ext.user_default.blender_scene_assistant.bsa.ui.avatar import (
        BSA_GGT_assistant_launcher,
        assistant_asset_loaded,
    )
    from bl_ext.user_default.blender_scene_assistant.bsa.ui.panel import (
        BSA_PT_scene_assistant,
    )

    if BSA_PT_scene_assistant.bl_category != "BSA":
        raise AssertionError("Installed sidebar category is not the Blender-safe BSA label")
    if BSA_PT_scene_assistant.bl_label != "场景领航员":
        raise AssertionError("Installed panel title is not Chinese")
    if BSA_OT_open_assistant.bl_label != "打开场景领航员":
        raise AssertionError("Installed assistant launcher is missing")
    if BSA_OT_open_print_part.bl_label != "打开 3D 打印零件":
        raise AssertionError("Installed print-part popup operator is missing")
    if BSA_OT_launch_assistant.bl_label != "启动 3D 打印零件助手":
        raise AssertionError("Installed assistant gizmo does not open product workflow")
    if BSA_OT_test_provider_connection.bl_label != "测试连接":
        raise AssertionError("Installed provider connection operator is missing")
    if BSA_OT_cancel_provider_connection.bl_label != "取消连接测试":
        raise AssertionError("Installed provider cancellation operator is missing")
    if BSA_GGT_assistant_launcher.bl_label != "3D 打印零件助手入口":
        raise AssertionError("Installed assistant avatar gizmo is missing")
    if not assistant_asset_loaded():
        raise AssertionError("Installed assistant avatar image did not load")
    if BSA_OT_preview_plan.bl_label != "生成预览":
        raise AssertionError("Installed preview button is not Chinese")
    if BSA_OT_confirm_plan.bl_label != "确认并执行":
        raise AssertionError("Installed confirm button is not Chinese")
    if BSA_OT_preview_instruction.bl_label != "解析并生成预览":
        raise AssertionError("Installed instruction button is not Chinese")
    if BSA_OT_start_ai_planning.bl_label != "同意并调用 AI":
        raise AssertionError("Installed AI consent operator is missing")
    if BSA_OT_cancel_ai_planning.bl_label != "取消 AI 规划":
        raise AssertionError("Installed AI cancellation operator is missing")
    if BSA_OT_discard_ai_request.bl_label != "不发送":
        raise AssertionError("Installed AI discard operator is missing")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    desk = add_cube("Desk", (0.0, 0.0, 0.5), (2.0, 1.0, 0.5))
    lamp = add_cube("Lamp", (0.0, 0.0, 0.5), (0.2, 0.2, 0.5))
    lamp_before = tuple(lamp.matrix_world.translation)

    settings = bpy.context.scene.bsa_settings
    provider = bpy.context.window_manager.bsa_provider_session
    if provider.connection_status != "NOT_TESTED":
        raise AssertionError("Installed provider session did not start untested")
    secret = "sk-bsa-installed-save-probe-4f91"
    provider.api_key = secret
    saved = REPOSITORY_ROOT / "benchmarks" / "results" / "installed-provider-secret-probe.blend"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.unlink(missing_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(saved), copy=True, compress=False)
    if secret.encode("utf-8") in saved.read_bytes():
        raise AssertionError("Installed session API key persisted into the blend file")
    saved.unlink(missing_ok=True)
    provider.api_key = ""
    if settings.assistant_status != "IDLE" or not settings.show_avatar:
        raise AssertionError("Installed assistant did not start idle")
    settings.instruction = "把 Lamp 放到 Desk 右侧，并锁定 Desk"
    if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
        raise AssertionError("Installed instruction preview operator failed")
    parsed_plan = json.loads(settings.plan_json)
    if parsed_plan["source"] != "local_parser":
        raise AssertionError("Installed instruction did not use the local parser")
    if settings.assistant_status != "PLAN_READY":
        raise AssertionError("Installed assistant did not enter plan-ready state")
    if settings.last_user_message != settings.instruction:
        raise AssertionError("Installed conversation did not retain the user message")
    if settings.source_object != lamp or settings.target_object != desk:
        raise AssertionError("Installed instruction did not populate object fields")
    if tuple(lamp.matrix_world.translation) != lamp_before:
        raise AssertionError("Installed preview changed the scene")
    settings.region = "left"
    if settings.plan_json:
        raise AssertionError("Installed preview did not expire after input changed")
    if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
        raise AssertionError("Installed preview could not be regenerated")
    if bpy.ops.bsa.confirm_plan() != {"FINISHED"}:
        raise AssertionError("Installed confirm operator failed")

    result = json.loads(settings.result_json)
    if result["status"] != "COMMITTED" or not result["verification"]["passed"]:
        raise AssertionError(f"Installed execution failed: {result}")
    if not settings.result_text.startswith("成功"):
        raise AssertionError("Installed UI did not show a clear Chinese result")
    if settings.assistant_status != "SUCCESS":
        raise AssertionError("Installed assistant did not enter success state")
    if settings.plan_json:
        raise AssertionError("Installed committed plan remained executable")
    human_result = settings.result_text

    move_before = tuple(lamp.matrix_world.translation)
    settings.instruction = "Lamp 向左移动 20 厘米"
    if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
        raise AssertionError("Installed move preview failed")
    move_plan = json.loads(settings.plan_json)
    if move_plan["actions"][0]["type"] != "move":
        raise AssertionError("Installed move instruction produced the wrong action")
    if tuple(lamp.matrix_world.translation) != move_before:
        raise AssertionError("Installed move preview changed the scene")
    if bpy.ops.bsa.confirm_plan() != {"FINISHED"}:
        raise AssertionError("Installed move execution failed")
    move_after = tuple(lamp.matrix_world.translation)
    if abs((move_after[0] - move_before[0]) + 0.2) > 1e-4:
        raise AssertionError("Installed move instruction used the wrong distance")

    if not desk.hide_select:
        raise AssertionError("Installed placement did not lock Desk")
    settings.instruction = "解除锁定 Desk"
    if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
        raise AssertionError("Installed unlock preview failed")
    unlock_plan = json.loads(settings.plan_json)
    if unlock_plan["actions"][0]["type"] != "unlock":
        raise AssertionError("Installed unlock instruction produced the wrong action")
    if bpy.ops.bsa.confirm_plan() != {"FINISHED"} or desk.hide_select:
        raise AssertionError("Installed unlock instruction did not unlock Desk")

    if bpy.ops.bsa.clear() != {"FINISHED"} or settings.assistant_status != "IDLE":
        raise AssertionError("Installed assistant did not clear to idle")

    installed_ai_review_before = tuple(lamp.matrix_world.translation)
    settings.instruction = "重新安排 Lamp 和 Desk，让画面更紧凑"
    if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
        raise AssertionError("Installed AI request did not enter data review")
    if settings.assistant_status != "AI_REVIEW":
        raise AssertionError("Installed AI request skipped data review")
    pending = json.loads(provider.pending_context_json)
    pending_names = {
        item["name"] for item in pending["scene_context"]["objects"]
    }
    if pending_names != {"Desk", "Lamp"}:
        raise AssertionError("Installed AI data review showed the wrong objects")
    if tuple(lamp.matrix_world.translation) != installed_ai_review_before:
        raise AssertionError("Installed AI data review changed the scene")
    if bpy.ops.bsa.discard_ai_request() != {"FINISHED"}:
        raise AssertionError("Installed AI request could not be discarded")
    if settings.assistant_status != "IDLE" or provider.pending_context_json:
        raise AssertionError("Installed AI data review was not cleared")

    scene_before_provider_error = tuple(lamp.matrix_world.translation)
    provider.api_base = "http://api.example.com/v1"
    if bpy.ops.bsa.test_provider_connection() != {"CANCELLED"}:
        raise AssertionError("Installed unsafe provider URL was not rejected")
    if tuple(lamp.matrix_world.translation) != scene_before_provider_error:
        raise AssertionError("Installed provider error changed the scene")
    if settings.plan_json:
        raise AssertionError("Installed provider error created a plan")

    provider.api_base = "https://api.example.com/v1"
    provider.api_key = "sk-installed-offline-mode-probe"
    if bpy.app.online_access:
        raise AssertionError("Installed factory-startup test expected offline mode")
    if bpy.ops.bsa.test_provider_connection() != {"CANCELLED"}:
        raise AssertionError("Installed Provider ignored Blender offline mode")
    if provider.connection_status != "ERROR" or "禁止" not in provider.connection_message:
        raise AssertionError("Installed Provider did not explain Blender offline mode")
    if tuple(lamp.matrix_world.translation) != scene_before_provider_error:
        raise AssertionError("Installed offline Provider test changed the scene")
    provider.api_key = ""

    report = {
        "blender_version": bpy.app.version_string,
        "installed_extension_enabled": True,
        "preview_was_read_only": True,
        "execution_status": result["status"],
        "verification_passed": result["verification"]["passed"],
        "human_result": human_result,
        "move_instruction_passed": True,
        "unlock_instruction_passed": True,
        "assistant_avatar_registered": True,
        "assistant_state_flow_passed": True,
        "provider_ui_registered": True,
        "session_key_not_persisted": True,
        "provider_error_scene_unchanged": True,
        "online_access_respected": True,
        "ai_data_review_is_read_only": True,
        "ai_consent_controls_registered": True,
    }
    output = REPOSITORY_ROOT / "benchmarks" / "results" / "m2_installed_results.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("BSA_INSTALLED_RESULT=" + json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
