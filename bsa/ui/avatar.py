"""3D 视图中的可点击助手形象。"""

from __future__ import annotations

from pathlib import Path

import bpy
import bpy.utils.previews
import gpu
from gpu_extras.batch import batch_for_shader

from ..application.assistant_state import AssistantStatus, presentation_for
from ..application.ui_presentation import AVATAR_HIT_RADIUS, AVATAR_SIZE_PX


_PREVIEWS = None
_IMAGE = None
_DRAW_HANDLE = None
_SHADER = None
_ICON_KEY = "scene_pilot_idle"
_ASSET_PATH = Path(__file__).resolve().parents[1] / "assets" / "scene_pilot_idle.png"


def _draw_avatar() -> None:
    """在每个 3D 视图右下角按实际像素尺寸绘制助手。"""

    context = bpy.context
    scene = getattr(context, "scene", None)
    region = getattr(context, "region", None)
    settings = getattr(scene, "bsa_settings", None)
    if region is None or settings is None or not settings.show_avatar:
        return

    global _IMAGE, _SHADER
    if _IMAGE is None:
        try:
            _IMAGE = bpy.data.images.load(str(_ASSET_PATH), check_existing=False)
        except (AttributeError, RuntimeError):
            return
    if _SHADER is None:
        _SHADER = gpu.shader.from_builtin("IMAGE")
    size = AVATAR_SIZE_PX
    center_x = max(56.0, region.width - 74.0)
    center_y = 74.0
    half = size / 2.0
    batch = batch_for_shader(
        _SHADER,
        "TRI_FAN",
        {
            "pos": (
                (center_x - half, center_y - half),
                (center_x + half, center_y - half),
                (center_x + half, center_y + half),
                (center_x - half, center_y + half),
            ),
            "texCoord": ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        },
    )
    gpu.state.blend_set("ALPHA")
    try:
        _SHADER.bind()
        _SHADER.uniform_sampler("image", gpu.texture.from_image(_IMAGE))
        batch.draw(_SHADER)
    finally:
        gpu.state.blend_set("NONE")


def register_assets() -> None:
    """加载本地指定的助手图像；来源与分发限制见资产说明。"""

    global _DRAW_HANDLE, _IMAGE, _PREVIEWS
    if _PREVIEWS is not None:
        return
    if not _ASSET_PATH.is_file():
        raise RuntimeError(f"Assistant asset is missing: {_ASSET_PATH}")
    _PREVIEWS = bpy.utils.previews.new()
    _PREVIEWS.load(_ICON_KEY, str(_ASSET_PATH), "IMAGE")
    if not bpy.app.background:
        _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            _draw_avatar,
            (),
            "WINDOW",
            "POST_PIXEL",
        )


def unregister_assets() -> None:
    """释放 Blender 预览图资源。"""

    global _DRAW_HANDLE, _IMAGE, _PREVIEWS, _SHADER
    if _DRAW_HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        _DRAW_HANDLE = None
    _SHADER = None
    if _IMAGE is not None:
        try:
            bpy.data.images.remove(_IMAGE)
        except (AttributeError, ReferenceError):
            pass
        _IMAGE = None
    if _PREVIEWS is not None:
        bpy.utils.previews.remove(_PREVIEWS)
        _PREVIEWS = None


def assistant_icon_id() -> int:
    """返回 Blender 可绘制的助手图像 ID。"""

    if _PREVIEWS is None:
        return 0
    return _PREVIEWS[_ICON_KEY].icon_id


def assistant_asset_loaded() -> bool:
    """返回资源是否已由 Blender 解码；后台模式不会分配 UI 图标编号。"""

    return (
        _PREVIEWS is not None
        and _ICON_KEY in _PREVIEWS
        and tuple(_PREVIEWS[_ICON_KEY].image_size) != (0, 0)
    )


class BSA_GGT_assistant_launcher(bpy.types.GizmoGroup):
    """固定在 3D 视图右下角的助手启动按钮。"""

    bl_idname = "BSA_GGT_assistant_launcher"
    bl_label = "场景领航员入口"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"PERSISTENT", "SCALE"}

    @classmethod
    def poll(cls, context: object) -> bool:
        scene = getattr(context, "scene", None)
        settings = getattr(scene, "bsa_settings", None)
        return (
            not bpy.app.background
            and settings is not None
            and settings.show_avatar
        )

    def setup(self, _context: object) -> None:
        gizmo = self.gizmos.new("GIZMO_GT_button_2d")
        gizmo.target_set_operator("bsa.launch_assistant")
        gizmo.draw_options = {"BACKDROP"}
        gizmo.icon_value = assistant_icon_id()
        gizmo.color = (0.15, 0.72, 0.86)
        gizmo.color_highlight = (1.0, 0.60, 0.15)
        # 保留极低透明度，Blender 才会为按钮生成可点击的选择区域。
        gizmo.alpha = 0.02
        gizmo.alpha_highlight = 0.12
        gizmo.backdrop_fill_alpha = 0.01
        gizmo.line_width = 1.5
        gizmo.scale_basis = AVATAR_HIT_RADIUS
        gizmo.use_tooltip = True
        self.launcher = gizmo

    def draw_prepare(self, context: object) -> None:
        region = context.region
        settings = context.scene.bsa_settings
        presentation = presentation_for(AssistantStatus(settings.assistant_status))
        self.launcher.matrix_basis[0][3] = max(56.0, region.width - 74.0)
        self.launcher.matrix_basis[1][3] = 74.0
        self.launcher.color = presentation.color
