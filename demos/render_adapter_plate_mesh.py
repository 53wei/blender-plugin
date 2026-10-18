"""为已经验证的转接板真实网格生成一张开发者检查图。"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
from mathutils import Vector


def output_path() -> Path:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(args) != 1:
        raise SystemExit("需要在 -- 后提供一个 PNG 输出路径")
    return Path(args[0]).resolve()


def main() -> None:
    output = output_path()
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 960
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "OBJECT"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    scene.display.shading.background_type = "VIEWPORT"
    scene.display.shading.background_color = (0.035, 0.045, 0.065)

    camera_data = bpy.data.cameras.new("BSA_AdapterPlate_Camera")
    camera = bpy.data.objects.new("BSA_AdapterPlate_Camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 0.105
    camera.location = (0.115, -0.085, 0.075)
    target = Vector((0.04, 0.02, 0.0015))
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()

    world = scene.world or bpy.data.worlds.new("BSA_AdapterPlate_World")
    scene.world = world
    world.color = (0.02, 0.025, 0.04)

    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)
    print(f"BSA_ADAPTER_PLATE_RENDER={output}")


if __name__ == "__main__":
    main()
