"""In-memory scene port for deterministic demos and fast tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from ..core.fingerprint import fingerprint_objects
from ..domain.scene import ObjectState, SceneSnapshot, Vector3


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

    def set_locked(self, object_id: str, locked: bool) -> None:
        self._objects[object_id] = replace(self._objects[object_id], locked=locked)
