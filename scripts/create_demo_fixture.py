"""生成可直接体验 M1 的桌子与台灯演示场景和前后对比图。"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import bpy
from mathutils import Vector

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from bsa.application.service import SceneEditingService  # noqa: E402
from bsa.blender_adapter.ids import ensure_stable_ids, stable_id  # noqa: E402
from bsa.blender_adapter.scene_port import BlenderScenePort  # noqa: E402
from bsa.core.fingerprint import fingerprint_snapshot  # noqa: E402
from bsa.core.validator import relevant_object_ids  # noqa: E402
from bsa.domain.actions import (  # noqa: E402
    ActionPlan,
    LockAction,
    PlaceOnAction,
    PreserveTransformConstraint,
)


def material(name: str, color: tuple[float, float, float, float], metallic: float = 0.0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = 0.38
    shader.inputs["Metallic"].default_value = metallic
    return mat


def apply_material(obj, mat) -> None:
    obj.data.materials.append(mat)


def add_cube(name: str, location, scale, mat):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    apply_material(obj, mat)
    return obj


def add_cylinder(name: str, location, radius: float, depth: float, mat):
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=radius, depth=depth, location=location)
    obj = bpy.context.active_object
    obj.name = name
    apply_material(obj, mat)
    return obj


def join_objects(objects: list, active, name: str):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active
    bpy.ops.object.join()
    active.name = name
    return active


def point_at(obj, target: tuple[float, float, float]) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def build_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for block in list(datablocks):
            datablocks.remove(block)

    wood = material("暖木色", (0.30, 0.095, 0.035, 1.0))
    dark_metal = material("深色金属", (0.035, 0.045, 0.065, 1.0), metallic=0.75)
    lamp_gold = material("台灯金色", (0.72, 0.30, 0.055, 1.0), metallic=0.35)
    floor_mat = material("地面", (0.12, 0.15, 0.20, 1.0))
    accent = material("装饰", (0.03, 0.30, 0.42, 1.0), metallic=0.1)

    floor = add_cube("Floor", (0.0, 0.0, -0.08), (5.8, 4.3, 0.08), floor_mat)
    floor.hide_select = True

    top = add_cube("DeskTop", (0.0, 0.0, 1.55), (2.2, 1.05, 0.14), wood)
    desk_parts = [top]
    for x in (-1.9, 1.9):
        for y in (-0.78, 0.78):
            desk_parts.append(add_cube("DeskLeg", (x, y, 0.70), (0.11, 0.11, 0.70), dark_metal))
    desk = join_objects(desk_parts, top, "Desk")

    base = add_cylinder("LampBase", (-3.0, -2.0, 0.10), 0.36, 0.20, lamp_gold)
    stem = add_cylinder("LampStem", (-3.0, -2.0, 0.63), 0.055, 0.90, dark_metal)
    bpy.ops.mesh.primitive_cone_add(
        vertices=48,
        radius1=0.43,
        radius2=0.23,
        depth=0.46,
        location=(-3.0, -2.0, 1.23),
    )
    shade = bpy.context.active_object
    shade.name = "LampShade"
    apply_material(shade, lamp_gold)
    lamp = join_objects([base, stem, shade], base, "Lamp")

    add_cube("Notebook", (-0.55, 0.0, 1.76), (0.48, 0.35, 0.035), accent)

    bpy.ops.object.camera_add(location=(7.0, -8.5, 5.6))
    camera = bpy.context.active_object
    camera.name = "DemoCamera"
    camera.data.lens = 53
    point_at(camera, (0.0, 0.0, 1.15))
    bpy.context.scene.camera = camera

    bpy.ops.object.light_add(type="AREA", location=(2.5, -3.5, 7.0))
    key = bpy.context.active_object
    key.data.energy = 950
    key.data.shape = "DISK"
    key.data.size = 4.5
    point_at(key, (0.0, 0.0, 1.0))

    bpy.ops.object.light_add(type="AREA", location=(-4.0, -1.0, 4.2))
    fill = bpy.context.active_object
    fill.data.energy = 600
    fill.data.color = (0.55, 0.72, 1.0)
    fill.data.size = 3.0
    point_at(fill, (-1.0, 0.0, 1.0))

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 960
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.025, 0.035, 0.055)
    scene.view_settings.look = "AgX - Medium High Contrast"
    return scene, desk, lamp


def render(scene, path: Path) -> None:
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main() -> int:
    fixture_dir = REPOSITORY_ROOT / "tests" / "fixtures"
    image_dir = REPOSITORY_ROOT / "docs" / "images"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    scene, desk, lamp = build_scene()
    ensure_stable_ids(scene.objects)
    fixture_path = fixture_dir / "desk_lamp_demo.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(fixture_path))
    render(scene, image_dir / "demo_before.png")

    plan = ActionPlan(
        schema_version="0.1",
        plan_id="visual-demo-001",
        source="test",
        scene_fingerprint="",
        requires_confirmation=False,
        actions=(
            PlaceOnAction(
                action_id="place-1",
                object_id=stable_id(lamp),
                target_id=stable_id(desk),
                region="right",
                clearance=0.0,
            ),
            LockAction(action_id="lock-1", object_id=stable_id(desk)),
        ),
        constraints=(
            PreserveTransformConstraint(
                constraint_id="preserve-1", object_id=stable_id(desk)
            ),
        ),
        user_summary="将 Lamp 放到 Desk 右侧并锁定 Desk",
    )
    port = BlenderScenePort(scene)
    plan = replace(
        plan,
        scene_fingerprint=fingerprint_snapshot(port.read_snapshot(), relevant_object_ids(plan)),
    )
    result = SceneEditingService(port).execute_plan(plan)
    if result.status != "COMMITTED":
        raise AssertionError(result.to_dict())
    render(scene, image_dir / "demo_after.png")
    print(f"BSA_DEMO_FIXTURE={fixture_path}")
    print(f"BSA_DEMO_RESULT={result.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
