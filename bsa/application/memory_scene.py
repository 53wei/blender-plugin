"""In-memory scene port for deterministic demos and fast tests."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from ..core.fingerprint import fingerprint_objects
from ..domain.scene import BoundingBox, ObjectState, SceneSnapshot, Vector3


def translation_matrix(location: Vector3) -> tuple[float, ...]:
    """Build a row-major 4x4 translation matrix."""
    x, y, z = location
    return (
        1.0,
        0.0,
        0.0,
        x,
        0.0,
        1.0,
        0.0,
        y,
        0.0,
        0.0,
        1.0,
        z,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def _composed_matrix(
    location: Vector3,
    rotation: Vector3,
    scale: Vector3,
) -> tuple[float, ...]:
    """Build an XYZ-Euler transform matrix for deterministic memory tests."""

    rx, ry, rz = rotation
    sx, sy, sz = scale
    cx, sxn = math.cos(rx), math.sin(rx)
    cy, syn = math.cos(ry), math.sin(ry)
    cz, szn = math.cos(rz), math.sin(rz)
    # Blender's XYZ Euler is equivalent to Rz @ Ry @ Rx for column vectors.
    r00 = cz * cy
    r01 = cz * syn * sxn - szn * cx
    r02 = cz * syn * cx + szn * sxn
    r10 = szn * cy
    r11 = szn * syn * sxn + cz * cx
    r12 = szn * syn * cx - cz * sxn
    r20 = -syn
    r21 = cy * sxn
    r22 = cy * cx
    x, y, z = location
    return (
        r00 * sx,
        r01 * sy,
        r02 * sz,
        x,
        r10 * sx,
        r11 * sy,
        r12 * sz,
        y,
        r20 * sx,
        r21 * sy,
        r22 * sz,
        z,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def _bbox_with_dimensions(state: ObjectState, dimensions: Vector3) -> BoundingBox:
    half = tuple(value / 2.0 for value in dimensions)
    center = state.bbox_world.center
    minimum = tuple(value - size for value, size in zip(center, half, strict=True))
    maximum = tuple(value + size for value, size in zip(center, half, strict=True))
    return state.bbox_world.from_min_max(minimum, maximum)  # type: ignore[arg-type]


class MemoryScenePort:
    """A faithful state port without any Blender dependency."""

    def __init__(self, objects: tuple[ObjectState, ...], scene_name: str = "M1 Demo") -> None:
        self._objects = {obj.object_id: obj for obj in objects}
        self._scene_name = scene_name

    def read_snapshot(self) -> SceneSnapshot:
        objects = tuple(sorted(self._objects.values(), key=lambda item: item.object_id))
        return SceneSnapshot(
            schema_version="0.1",
            snapshot_id=str(uuid4()),
            scene_name=self._scene_name,
            unit_scale=1.0,
            objects=objects,
            active_camera_id=None,
            created_at=datetime.now(UTC).isoformat(),
            fingerprint=fingerprint_objects(objects),
        )

    def capture_checkpoint(self, object_ids: tuple[str, ...]) -> dict[str, ObjectState]:
        return {object_id: self._objects[object_id] for object_id in object_ids}

    def restore_checkpoint(self, checkpoint: dict[str, ObjectState]) -> bool:
        self._objects.update(checkpoint)
        return all(self._objects[object_id] == state for object_id, state in checkpoint.items())

    def apply_location(self, object_id: str, location_world: Vector3) -> None:
        current = self._objects[object_id]
        delta = tuple(
            new - old
            for new, old in zip(location_world, current.location_world, strict=True)
        )
        self._objects[object_id] = replace(
            current,
            location_world=location_world,
            matrix_world=translation_matrix(location_world),
            bbox_world=current.bbox_world.translated(delta),  # type: ignore[arg-type]
        )

    def apply_rotation(self, object_id: str, axis: str, angle_radians: float) -> None:
        current = self._objects[object_id]
        axis_index = {"x": 0, "y": 1, "z": 2}[axis]
        rotation = list(current.rotation_euler)
        rotation[axis_index] += angle_radians
        width, depth, height = current.dimensions_world
        cosine = abs(math.cos(angle_radians))
        sine = abs(math.sin(angle_radians))
        if axis == "x":
            dimensions = (width, cosine * depth + sine * height, sine * depth + cosine * height)
        elif axis == "y":
            dimensions = (cosine * width + sine * height, depth, sine * width + cosine * height)
        else:
            dimensions = (cosine * width + sine * depth, sine * width + cosine * depth, height)
        rotation_tuple = tuple(rotation)
        self._objects[object_id] = replace(
            current,
            matrix_world=_composed_matrix(
                current.location_world,
                rotation_tuple,  # type: ignore[arg-type]
                current.scale,
            ),
            rotation_euler=rotation_tuple,  # type: ignore[arg-type]
            bbox_world=_bbox_with_dimensions(current, dimensions),
            dimensions_world=dimensions,
        )

    def apply_uniform_scale(self, object_id: str, factor: float) -> None:
        current = self._objects[object_id]
        scale = tuple(value * factor for value in current.scale)
        dimensions = tuple(value * factor for value in current.dimensions_world)
        self._objects[object_id] = replace(
            current,
            matrix_world=_composed_matrix(
                current.location_world,
                current.rotation_euler,
                scale,  # type: ignore[arg-type]
            ),
            scale=scale,  # type: ignore[arg-type]
            bbox_world=_bbox_with_dimensions(current, dimensions),
            dimensions_world=dimensions,  # type: ignore[arg-type]
        )

    def set_locked(self, object_id: str, locked: bool) -> None:
        self._objects[object_id] = replace(self._objects[object_id], locked=locked)
