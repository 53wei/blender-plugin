"""Transactional Blender implementation of the application scene port."""

from __future__ import annotations

from dataclasses import dataclass

import bpy
from mathutils import Matrix, Vector

from .ids import LOCK_PROPERTY, ensure_stable_ids, stable_id
from .scene_reader import read_scene_snapshot
from ..domain.errors import DomainError, ErrorCode
from ..domain.scene import SceneSnapshot, Vector3
from ..infra.config import LOCK_TRANSFORM_EPS


@dataclass(frozen=True)
class BlenderObjectCheckpoint:
    matrix_world: tuple[float, ...]
    locked: bool
    hide_select: bool


class BlenderScenePort:
    """Apply authorized changes to the active Blender scene."""

    def __init__(self, scene: object | None = None) -> None:
        self._scene = scene or bpy.context.scene

    def read_snapshot(self) -> SceneSnapshot:
        return read_scene_snapshot(self._scene)

    def _object(self, object_id: str) -> object:
        ensure_stable_ids(self._scene.objects)
        for obj in self._scene.objects:
            if stable_id(obj) == object_id:
                return obj
        raise DomainError(
            ErrorCode.OBJECT_NOT_FOUND,
            "Object disappeared during execution",
            {"object_id": object_id},
        )

    def capture_checkpoint(
        self, object_ids: tuple[str, ...]
    ) -> dict[str, BlenderObjectCheckpoint]:
        checkpoint: dict[str, BlenderObjectCheckpoint] = {}
        for object_id in object_ids:
            obj = self._object(object_id)
            checkpoint[object_id] = BlenderObjectCheckpoint(
                matrix_world=tuple(
                    float(obj.matrix_world[row][column])
                    for row in range(4)
                    for column in range(4)
                ),
                locked=bool(obj.get(LOCK_PROPERTY, False)),
                hide_select=bool(obj.hide_select),
            )
        return checkpoint

    def restore_checkpoint(self, checkpoint: dict[str, BlenderObjectCheckpoint]) -> bool:
        for object_id, state in checkpoint.items():
            obj = self._object(object_id)
            rows = [state.matrix_world[index : index + 4] for index in range(0, 16, 4)]
            obj.matrix_world = Matrix(rows)
            obj[LOCK_PROPERTY] = state.locked
            obj.hide_select = state.hide_select
        bpy.context.view_layer.update()
        for object_id, state in checkpoint.items():
            obj = self._object(object_id)
            current = tuple(
                float(obj.matrix_world[row][column]) for row in range(4) for column in range(4)
            )
            if max(abs(left - right) for left, right in zip(current, state.matrix_world, strict=True)) > LOCK_TRANSFORM_EPS:
                return False
            if bool(obj.get(LOCK_PROPERTY, False)) is not state.locked:
                return False
        return True

    def apply_location(self, object_id: str, location_world: Vector3) -> None:
        obj = self._object(object_id)
        if bool(obj.get(LOCK_PROPERTY, False)):
            raise DomainError(
                ErrorCode.OBJECT_LOCKED,
                "Locked object cannot be moved",
                {"object_id": object_id},
            )
        matrix = obj.matrix_world.copy()
        matrix.translation = Vector(location_world)
        obj.matrix_world = matrix
        bpy.context.view_layer.update()

    def set_locked(self, object_id: str, locked: bool) -> None:
        obj = self._object(object_id)
        obj[LOCK_PROPERTY] = locked
        obj.hide_select = locked
