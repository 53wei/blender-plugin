"""Exercise extension registration and the Preview/Confirm UI operators in Blender."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import bpy

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def load_extension():
    module_name = "blender_scene_assistant_integration"
    spec = importlib.util.spec_from_file_location(
        module_name,
        REPOSITORY_ROOT / "__init__.py",
        submodule_search_locations=[str(REPOSITORY_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load extension package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def add_cube(name: str, location: tuple[float, float, float], scale: tuple[float, float, float]):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.context.view_layer.update()
    return obj


def main() -> int:
    extension = load_extension()
    registered = False
    try:
        extension.register()
        registered = True
        if not hasattr(bpy.types.Scene, "bsa_settings"):
            raise AssertionError("Scene property was not registered")
        if not hasattr(bpy.types.WindowManager, "bsa_provider_session"):
            raise AssertionError("Provider session property was not registered")
        if hasattr(bpy.types.Scene, "bsa_provider_session"):
            raise AssertionError("Provider credentials must not belong to Scene")

        from blender_scene_assistant_integration.bsa.ui.avatar import (
            BSA_GGT_assistant_launcher,
            assistant_asset_loaded,
        )
        from blender_scene_assistant_integration.bsa.ui.operators import (
            BSA_OT_cancel_ai_planning,
            BSA_OT_cancel_provider_connection,
            BSA_OT_confirm_camera,
            BSA_OT_confirm_plan,
            BSA_OT_discard_ai_request,
            BSA_OT_export_png,
            BSA_OT_import_models,
            BSA_OT_launch_assistant,
            BSA_OT_open_assistant,
            BSA_OT_preview_align,
            BSA_OT_preview_camera,
            BSA_OT_preview_grid,
            BSA_OT_preview_ground,
            BSA_OT_preview_instruction,
            BSA_OT_preview_plan,
            BSA_OT_preview_rotate,
            BSA_OT_preview_scale,
            BSA_OT_start_ai_planning,
            BSA_OT_test_provider_connection,
        )
        from blender_scene_assistant_integration.bsa.ui.panel import (
            BSA_PT_scene_assistant,
        )

        if BSA_PT_scene_assistant.bl_category != "BSA":
            raise AssertionError("Sidebar category is not the Blender-safe BSA label")
        if BSA_PT_scene_assistant.bl_label != "场景领航员":
            raise AssertionError("Panel title is not Chinese")
        if BSA_OT_open_assistant.bl_label != "打开场景领航员":
            raise AssertionError("Assistant launcher operator is not registered")
        if BSA_OT_launch_assistant.bl_label != "启动场景领航员":
            raise AssertionError("Assistant gizmo bridge is not registered")
        if BSA_OT_test_provider_connection.bl_label != "测试连接":
            raise AssertionError("Provider connection operator is not registered")
        if BSA_OT_cancel_provider_connection.bl_label != "取消连接测试":
            raise AssertionError("Provider cancellation operator is not registered")
        if BSA_OT_start_ai_planning.bl_label != "同意并调用 AI":
            raise AssertionError("AI planning operator is not registered")
        if BSA_OT_cancel_ai_planning.bl_label != "取消 AI 规划":
            raise AssertionError("AI cancellation operator is not registered")
        if BSA_OT_discard_ai_request.bl_label != "不发送":
            raise AssertionError("AI data review discard operator is not registered")
        if BSA_GGT_assistant_launcher.bl_label != "场景领航员入口":
            raise AssertionError("Assistant avatar gizmo is not registered")
        if not assistant_asset_loaded():
            raise AssertionError("Assistant avatar image was not loaded")
        if BSA_OT_preview_plan.bl_label != "生成预览":
            raise AssertionError("Preview button is not Chinese")
        if BSA_OT_confirm_plan.bl_label != "确认并执行":
            raise AssertionError("Confirm button is not Chinese")
        if BSA_OT_preview_instruction.bl_label != "解析并生成预览":
            raise AssertionError("Instruction preview button is not Chinese")
        guided_operators = {
            BSA_OT_import_models.bl_idname,
            BSA_OT_preview_ground.bl_idname,
            BSA_OT_preview_align.bl_idname,
            BSA_OT_preview_grid.bl_idname,
            BSA_OT_preview_rotate.bl_idname,
            BSA_OT_preview_scale.bl_idname,
            BSA_OT_preview_camera.bl_idname,
            BSA_OT_confirm_camera.bl_idname,
            BSA_OT_export_png.bl_idname,
        }
        if len(guided_operators) != 9:
            raise AssertionError("Guided workflow operators were not registered uniquely")

        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        desk = add_cube("Desk", (0.0, 0.0, 0.5), (2.0, 1.0, 0.5))
        lamp = add_cube("Lamp", (0.0, 0.0, 0.5), (0.2, 0.2, 0.5))
        lamp_before = tuple(lamp.matrix_world.translation)

        settings = bpy.context.scene.bsa_settings
        provider = bpy.context.window_manager.bsa_provider_session
        if provider.connection_status != "NOT_TESTED":
            raise AssertionError("Provider session did not start untested")
        secret = "sk-bsa-save-probe-7d2a"
        provider.api_key = secret
        saved = REPOSITORY_ROOT / "benchmarks" / "results" / "provider-secret-probe.blend"
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.unlink(missing_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(saved), copy=True, compress=False)
        if secret.encode("utf-8") in saved.read_bytes():
            raise AssertionError("Session API key was persisted into the blend file")
        saved.unlink(missing_ok=True)
        provider.api_key = ""

        if settings.assistant_status != "IDLE" or not settings.show_avatar:
            raise AssertionError("Assistant did not start in the expected idle state")
        settings.instruction = "把 Lamp 放到 Desk 右侧，并锁定 Desk"

        preview_status = bpy.ops.bsa.preview_instruction()
        if preview_status != {"FINISHED"} or not settings.plan_json:
            raise AssertionError("Instruction preview did not produce a plan")
        parsed_plan = json.loads(settings.plan_json)
        if parsed_plan["source"] != "local_parser":
            raise AssertionError("Instruction did not use the local parser")
        if settings.assistant_status != "PLAN_READY":
            raise AssertionError("Assistant did not enter plan-ready state")
        if settings.last_user_message != settings.instruction:
            raise AssertionError("Conversation did not retain the user instruction")
        if not settings.last_assistant_message:
            raise AssertionError("Conversation did not show the assistant plan")
        if settings.source_object != lamp or settings.target_object != desk:
            raise AssertionError("Instruction preview did not populate object fields")
        if tuple(lamp.matrix_world.translation) != lamp_before:
            raise AssertionError("Preview changed the scene before confirmation")

        settings.region = "left"
        if settings.plan_json:
            raise AssertionError("Changing placement settings did not invalidate the preview")
        if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
            raise AssertionError("Preview could not be regenerated after invalidation")

        confirm_status = bpy.ops.bsa.confirm_plan()
        result = json.loads(settings.result_json)
        if confirm_status != {"FINISHED"} or result["status"] != "COMMITTED":
            raise AssertionError(f"Confirm failed: {result}")
        if not result["verification"]["passed"]:
            raise AssertionError("UI execution did not pass verification")
        if not settings.result_text.startswith("成功"):
            raise AssertionError("UI did not present a clear Chinese success message")
        if settings.assistant_status != "SUCCESS":
            raise AssertionError("Assistant did not enter success state")
        if settings.plan_json:
            raise AssertionError("Committed plan remained executable after success")
        human_result = settings.result_text

        move_before = tuple(lamp.matrix_world.translation)
        settings.instruction = "Lamp 向左移动 20 厘米"
        if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
            raise AssertionError("Move instruction preview failed")
        move_plan = json.loads(settings.plan_json)
        if move_plan["actions"][0]["type"] != "move":
            raise AssertionError("Move instruction did not create a move action")
        if tuple(lamp.matrix_world.translation) != move_before:
            raise AssertionError("Move preview changed the scene before confirmation")
        if bpy.ops.bsa.confirm_plan() != {"FINISHED"}:
            raise AssertionError("Move instruction execution failed")
        move_after = tuple(lamp.matrix_world.translation)
        if abs((move_after[0] - move_before[0]) + 0.2) > 1e-4:
            raise AssertionError("Move instruction did not move Lamp left by 20 cm")

        if not desk.hide_select:
            raise AssertionError("Desk was not locked by the placement instruction")
        settings.instruction = "解除锁定 Desk"
        if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
            raise AssertionError("Unlock instruction preview failed")
        unlock_plan = json.loads(settings.plan_json)
        if unlock_plan["actions"][0]["type"] != "unlock":
            raise AssertionError("Unlock instruction did not create an unlock action")
        if bpy.ops.bsa.confirm_plan() != {"FINISHED"} or desk.hide_select:
            raise AssertionError("Unlock instruction did not unlock Desk")

        if bpy.ops.bsa.clear() != {"FINISHED"}:
            raise AssertionError("Assistant clear action failed")
        if settings.assistant_status != "IDLE":
            raise AssertionError("Assistant did not return to idle after clear")

        scene_before_ai_review = tuple(lamp.matrix_world.translation)
        settings.instruction = "重新安排 Lamp 和 Desk，让画面更紧凑"
        if bpy.ops.bsa.preview_instruction() != {"FINISHED"}:
            raise AssertionError("Vague instruction did not enter AI data review")
        if settings.assistant_status != "AI_REVIEW":
            raise AssertionError("Assistant did not enter AI review state")
        if not provider.pending_context_json or not provider.pending_data_preview:
            raise AssertionError("AI review did not show the pending data summary")
        pending = json.loads(provider.pending_context_json)
        if {obj["name"] for obj in pending["scene_context"]["objects"]} != {"Desk", "Lamp"}:
            raise AssertionError("AI review did not minimize context to named objects")
        if settings.plan_json or tuple(lamp.matrix_world.translation) != scene_before_ai_review:
            raise AssertionError("AI data review changed the scene or created a plan")
        if bpy.ops.bsa.discard_ai_request() != {"FINISHED"}:
            raise AssertionError("AI data review could not be discarded")
        if provider.pending_context_json or settings.assistant_status != "IDLE":
            raise AssertionError("Discarding AI data did not clear the session request")

        scene_before_provider_error = tuple(lamp.matrix_world.translation)
        provider.api_base = "http://api.example.com/v1"
        provider.api_key = ""
        if bpy.ops.bsa.test_provider_connection() != {"CANCELLED"}:
            raise AssertionError("Unsafe provider URL was not rejected before network access")
        if tuple(lamp.matrix_world.translation) != scene_before_provider_error:
            raise AssertionError("Provider configuration error changed the scene")
        if settings.plan_json:
            raise AssertionError("Provider configuration error created a plan")

        provider.api_base = "https://api.example.com/v1"
        provider.api_key = "sk-offline-mode-probe"
        if bpy.app.online_access:
            raise AssertionError("Factory-startup test expected Blender offline mode")
        if bpy.ops.bsa.test_provider_connection() != {"CANCELLED"}:
            raise AssertionError("Blender offline mode did not block Provider access")
        if provider.connection_status != "ERROR" or "禁止" not in provider.connection_message:
            raise AssertionError("Provider UI did not explain Blender offline mode")
        if tuple(lamp.matrix_world.translation) != scene_before_provider_error:
            raise AssertionError("Blocked online access changed the scene")
        provider.api_key = ""

        extension.unregister()
        registered = False
        if hasattr(bpy.types.Scene, "bsa_settings"):
            raise AssertionError("Scene property remained after unregister")
        extension.register()
        registered = True
        extension.unregister()
        registered = False

        report = {
            "blender_version": bpy.app.version_string,
            "registration_cycle_passed": True,
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
        }
        output = REPOSITORY_ROOT / "benchmarks" / "results" / "m2_ui_results.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("BSA_UI_RESULT=" + json.dumps(report, ensure_ascii=True))
        return 0
    finally:
        if registered:
            extension.unregister()


if __name__ == "__main__":
    raise SystemExit(main())
