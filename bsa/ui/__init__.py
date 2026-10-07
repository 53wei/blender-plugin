"""Blender sidebar UI registration."""

from __future__ import annotations

import bpy

from .avatar import (
    BSA_GGT_assistant_launcher,
    register_assets,
    unregister_assets,
)
from .operators import (
    BSA_OT_cancel_ai_planning,
    BSA_OT_cancel_provider_connection,
    BSA_OT_clear,
    BSA_OT_confirm_plan,
    BSA_OT_discard_ai_request,
    BSA_OT_launch_assistant,
    BSA_OT_open_assistant,
    BSA_OT_preview_instruction,
    BSA_OT_preview_plan,
    BSA_OT_start_ai_planning,
    BSA_OT_test_provider_connection,
    cancel_provider_task,
)
from .panel import BSA_PT_scene_assistant
from .properties import BSAProviderSession, BSASettings

_CLASSES = (
    BSASettings,
    BSAProviderSession,
    BSA_OT_open_assistant,
    BSA_OT_launch_assistant,
    BSA_OT_preview_instruction,
    BSA_OT_preview_plan,
    BSA_OT_start_ai_planning,
    BSA_OT_cancel_ai_planning,
    BSA_OT_discard_ai_request,
    BSA_OT_test_provider_connection,
    BSA_OT_cancel_provider_connection,
    BSA_OT_confirm_plan,
    BSA_OT_clear,
    BSA_PT_scene_assistant,
    BSA_GGT_assistant_launcher,
)


def register() -> None:
    """Register property, operator, and panel classes."""
    register_assets()
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bsa_settings = bpy.props.PointerProperty(type=BSASettings)
    bpy.types.WindowManager.bsa_provider_session = bpy.props.PointerProperty(
        type=BSAProviderSession
    )


def unregister() -> None:
    """Remove property, operator, and panel classes."""
    cancel_provider_task()
    if hasattr(bpy.types.WindowManager, "bsa_provider_session"):
        del bpy.types.WindowManager.bsa_provider_session
    if hasattr(bpy.types.Scene, "bsa_settings"):
        del bpy.types.Scene.bsa_settings
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    unregister_assets()
