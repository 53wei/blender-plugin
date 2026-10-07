"""评测专用的公开合成对象，既可用于内存也可用于 Blender。"""

from __future__ import annotations

from bsa.application.memory_scene import MemoryScenePort, translation_matrix
from bsa.domain.scene import BoundingBox, ObjectState


def fixture_objects(locked_ids: tuple[str, ...] = ()) -> tuple[ObjectState, ...]:
    """创建 Desk/Lamp/Chair 的固定世界坐标快照数据。"""
    specs = (
        ("desk-id", "Desk", (0.0, 0.0, 0.5), (4.0, 2.0, 1.0)),
        ("lamp-id", "Lamp", (0.0, 0.0, 0.5), (0.4, 0.4, 1.0)),
        ("chair-id", "Chair", (4.0, 0.0, 0.5), (1.0, 1.0, 1.0)),
    )
    objects = []
    for object_id, name, location, dimensions in specs:
        low = tuple(value - size / 2 for value, size in zip(location, dimensions, strict=True))
        high = tuple(value + size / 2 for value, size in zip(location, dimensions, strict=True))
        objects.append(ObjectState(
            object_id=object_id, name=name, object_type="MESH",
            matrix_world=translation_matrix(location), location_world=location,
            rotation_euler=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0),
            bbox_world=BoundingBox.from_min_max(low, high), dimensions_world=dimensions,
            parent_id=None, locked=object_id in locked_ids, visible=True,
        ))
    return tuple(objects)


def memory_fixture(case: dict) -> MemoryScenePort:
    """每个任务使用独立场景，不继承上一任务的状态。"""
    return MemoryScenePort(fixture_objects(tuple(case.get("initial_locked", ()))))
