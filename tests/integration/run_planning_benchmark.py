"""Blender 4.5 固定任务评测：只在出厂启动的一次性夹具上执行。"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmarks.fixture import fixture_objects
from benchmarks.runner import main
from bsa.blender_adapter.ids import LOCK_PROPERTY, OBJECT_ID_PROPERTY
from bsa.blender_adapter.scene_port import BlenderScenePort


_owned_scene = None
_owned_objects = []
_owned_meshes = []
_original_scene = bpy.context.scene


def clean_fixture() -> None:
    """只移除本脚本创建的临时数据，不操作出厂场景或用户文件。"""
    global _owned_scene
    bpy.context.window.scene = _original_scene
    for obj in _owned_objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in _owned_meshes:
        bpy.data.meshes.remove(mesh)
    _owned_objects.clear()
    _owned_meshes.clear()
    if _owned_scene is not None:
        bpy.data.scenes.remove(_owned_scene)
        _owned_scene = None


def blender_fixture(case: dict) -> BlenderScenePort:
    """每个任务新建公开合成场景；待测动作仍经事务和执行器。"""
    global _owned_scene
    clean_fixture()
    _owned_scene = bpy.data.scenes.new("BSA_Evaluation_" + case["case_id"])
    bpy.context.window.scene = _owned_scene
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    for state in fixture_objects(tuple(case.get("initial_locked", ()))):
        vertices = [(x * state.dimensions_world[0] / 2,
                     y * state.dimensions_world[1] / 2,
                     z * state.dimensions_world[2] / 2)
                    for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        mesh = bpy.data.meshes.new(state.name + "_evaluation_mesh")
        mesh.from_pydata(vertices, [], faces)
        _owned_meshes.append(mesh)
        obj = bpy.data.objects.new(state.name, mesh)
        _owned_objects.append(obj)
        _owned_scene.collection.objects.link(obj)
        obj.location = state.location_world
        obj[OBJECT_ID_PROPERTY] = state.object_id
        obj[LOCK_PROPERTY] = state.locked
        obj.hide_select = state.locked
    bpy.context.view_layer.update()
    return BlenderScenePort(_owned_scene)


if __name__ == "__main__":
    if "--factory-startup" not in sys.argv or bpy.data.filepath:
        raise RuntimeError("为保护用户场景，必须使用 --factory-startup 且不能加载 .blend 文件")
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "live" in args and not bpy.app.online_access:
        raise RuntimeError("真实模型模式需要 Blender --online-mode")
    try:
        exit_code = main(args, scene_factory=blender_fixture,
                         engine="blender_" + bpy.app.version_string.replace(" ", "_"),
                         default_mode="replay")
    finally:
        clean_fixture()
    raise SystemExit(exit_code)
