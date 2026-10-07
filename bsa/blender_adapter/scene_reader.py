"""Read Blender objects into the immutable Scene IR."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from mathutils import Vector

from .ids import LOCK_PROPERTY, ensure_stable_ids, stable_id
from ..core.fingerprint import fingerprint_objects
from ..domain.scene import BoundingBox, ObjectState, SceneSnapshot


def _world_bbox(obj: object) -> BoundingBox:
    corners = [obj.matrix_world @ Vector(obj_corner) for obj_corner in obj.bound_box]
    minimum = tuple(min(corner[axis] for corner in corners) for axis in range(3))
    maximum = tuple(max(corner[axis] for corner in corners) for axis in range(3))
    return BoundingBox.from_min_max(minimum, maximum)  # type: ignore[arg-type]


def read_scene_snapshot(scene: object) -> SceneSnapshot:
    """Build a deterministic snapshot from a Blender scene on the main thread."""
    ensure_stable_ids(scene.objects)
    objects: list[ObjectState] = []
    for obj in scene.objects:
        bbox = _world_bbox(obj)
        matrix = tuple(float(obj.matrix_world[row][column]) for row in range(4) for column in range(4))
        translation = obj.matrix_world.translation
        rotation = obj.matrix_world.to_euler()
        scale = obj.matrix_world.to_scale()
        parent_id = stable_id(obj.parent) if obj.parent else None
        objects.append(
            ObjectState(
                object_id=stable_id(obj),
                name=obj.name,
                object_type=obj.type,
                matrix_world=matrix,
                location_world=tuple(float(value) for value in translation),  # type: ignore[arg-type]
                rotation_euler=tuple(float(value) for value in rotation),  # type: ignore[arg-type]
                scale=tuple(float(value) for value in scale),  # type: ignore[arg-type]
                bbox_world=bbox,
                dimensions_world=bbox.dimensions,
                parent_id=parent_id,
                locked=bool(obj.get(LOCK_PROPERTY, False)),
                visible=not obj.hide_get(),
            )
        )
    ordered = tuple(sorted(objects, key=lambda item: item.object_id))
    active_camera_id = stable_id(scene.camera) if scene.camera else None
    return SceneSnapshot(
        schema_version="0.1",
        snapshot_id=str(uuid4()),
        scene_name=scene.name,
        unit_scale=float(scene.unit_settings.scale_length or 1.0),
        objects=ordered,
        active_camera_id=active_camera_id,
        created_at=datetime.now(UTC).isoformat(),
        fingerprint=fingerprint_objects(ordered),
    )
