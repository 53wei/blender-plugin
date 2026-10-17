"""Blender 4.5 外壳装配预览创建器与创建型检查点。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import bpy

from .ids import ensure_stable_ids, stable_id
from .scene_port import BlenderObjectCheckpoint, BlenderScenePort
from ..domain.enclosure_preview import EnclosurePartSpec, EnclosurePartState
from ..domain.errors import DomainError, ErrorCode
from ..domain.scene import ObjectState

ENCLOSURE_ID_PROPERTY = "bsa_enclosure_id"
TRANSACTION_ID_PROPERTY = "bsa_creation_transaction_id"
PART_ID_PROPERTY = "bsa_enclosure_part_id"
PART_TYPE_PROPERTY = "bsa_enclosure_part_type"
SHAPE_PROPERTY = "bsa_enclosure_shape"


@dataclass(frozen=True)
class BlenderCreationCheckpoint:
    """创建事务开始前的完整既有对象状态。"""

    object_ids: tuple[str, ...]
    object_states: tuple[ObjectState, ...]
    transforms: dict[str, BlenderObjectCheckpoint]


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.")
    return cleaned[:48] or "preview"


def _box_geometry(
    dimensions: tuple[float, float, float],
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    half_x, half_y, half_z = (value / 2.0 for value in dimensions)
    vertices = [
        (-half_x, -half_y, -half_z),
        (half_x, -half_y, -half_z),
        (half_x, half_y, -half_z),
        (-half_x, half_y, -half_z),
        (-half_x, -half_y, half_z),
        (half_x, -half_y, half_z),
        (half_x, half_y, half_z),
        (-half_x, half_y, half_z),
    ]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return vertices, faces


def _cylinder_geometry(
    dimensions: tuple[float, float, float], segments: int = 32
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    radius = dimensions[0] / 2.0
    half_height = dimensions[2] / 2.0
    vertices = [
        (
            radius * math.cos(2.0 * math.pi * index / segments),
            radius * math.sin(2.0 * math.pi * index / segments),
            z,
        )
        for z in (-half_height, half_height)
        for index in range(segments)
    ]
    faces: list[tuple[int, ...]] = [
        tuple(reversed(range(segments))),
        tuple(range(segments, segments * 2)),
    ]
    for index in range(segments):
        next_index = (index + 1) % segments
        faces.append(
            (index, next_index, next_index + segments, index + segments)
        )
    return vertices, faces


class BlenderEnclosurePreviewPort:
    """只通过严格部件规格创建 Blender 预览对象。"""

    def __init__(self, scene: object | None = None) -> None:
        self._scene = scene or bpy.context.scene
        self._scene_port = BlenderScenePort(self._scene)

    def _millimetres_per_blender_unit(self) -> float:
        scale_length = float(self._scene.unit_settings.scale_length)
        if not math.isfinite(scale_length) or scale_length <= 0.0:
            raise DomainError(
                ErrorCode.PRECONDITION_FAILED,
                "Blender 场景单位比例必须是正有限数值",
                {"scale_length": scale_length},
            )
        return scale_length * 1000.0

    def enclosure_exists(self, enclosure_id: str) -> bool:
        return any(
            str(obj.get(ENCLOSURE_ID_PROPERTY, "")) == enclosure_id
            for obj in self._scene.objects
        ) or any(
            str(collection.get(ENCLOSURE_ID_PROPERTY, "")) == enclosure_id
            for collection in bpy.data.collections
        )

    def transaction_exists(self, transaction_id: str) -> bool:
        return any(
            str(obj.get(TRANSACTION_ID_PROPERTY, "")) == transaction_id
            for obj in self._scene.objects
        ) or any(
            str(collection.get(TRANSACTION_ID_PROPERTY, "")) == transaction_id
            for collection in bpy.data.collections
        )

    def capture_creation_checkpoint(
        self, transaction_id: str
    ) -> BlenderCreationCheckpoint:
        del transaction_id
        snapshot = self._scene_port.read_snapshot()
        object_ids = tuple(sorted(obj.object_id for obj in snapshot.objects))
        return BlenderCreationCheckpoint(
            object_ids=object_ids,
            object_states=snapshot.objects,
            transforms=self._scene_port.capture_checkpoint(object_ids),
        )

    def create_preview_parts(
        self,
        enclosure_id: str,
        transaction_id: str,
        parts: tuple[EnclosurePartSpec, ...],
    ) -> None:
        mm_per_unit = self._millimetres_per_blender_unit()
        collection = bpy.data.collections.new(
            f"BSA_Preview_{_safe_name(enclosure_id)}"
        )
        collection[ENCLOSURE_ID_PROPERTY] = enclosure_id
        collection[TRANSACTION_ID_PROPERTY] = transaction_id
        self._scene.collection.children.link(collection)

        for part in parts:
            dimensions = tuple(value / mm_per_unit for value in part.dimensions_mm)
            center = tuple(value / mm_per_unit for value in part.center_mm)
            if part.shape == "box":
                vertices, faces = _box_geometry(dimensions)
            elif part.shape == "cylinder":
                vertices, faces = _cylinder_geometry(dimensions)
            else:
                raise DomainError(
                    ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
                    "Blender 预览执行器不支持该部件形状",
                    {"part_id": part.part_id, "shape": part.shape},
                )

            object_name = (
                f"BSA_{_safe_name(enclosure_id)}_{_safe_name(part.part_id)}"
            )
            mesh = bpy.data.meshes.new(f"{object_name}_Mesh")
            mesh[TRANSACTION_ID_PROPERTY] = transaction_id
            mesh.from_pydata(vertices, [], faces)
            mesh.update(calc_edges=True)
            obj = bpy.data.objects.new(object_name, mesh)
            obj[ENCLOSURE_ID_PROPERTY] = enclosure_id
            obj[TRANSACTION_ID_PROPERTY] = transaction_id
            obj[PART_ID_PROPERTY] = part.part_id
            obj[PART_TYPE_PROPERTY] = part.part_type
            obj[SHAPE_PROPERTY] = part.shape
            collection.objects.link(obj)
            obj.location = center
            obj.display_type = "WIRE" if part.display_mode == "wire" else "SOLID"
            obj.show_name = part.display_mode == "wire"
            obj.show_in_front = part.display_mode == "wire"
            obj.color = self._part_color(part.part_type)

        ensure_stable_ids(collection.objects)
        bpy.context.view_layer.update()

    @staticmethod
    def _part_color(part_type: str) -> tuple[float, float, float, float]:
        if part_type == "board_proxy":
            return (0.05, 0.45, 0.16, 0.35)
        if part_type == "port_cutout_proxy":
            return (1.0, 0.25, 0.05, 0.6)
        if part_type == "lid":
            return (0.18, 0.42, 0.8, 0.25)
        return (0.12, 0.32, 0.72, 1.0)

    def read_created_parts(
        self, transaction_id: str
    ) -> tuple[EnclosurePartState, ...]:
        mm_per_unit = self._millimetres_per_blender_unit()
        bpy.context.view_layer.update()
        states: list[EnclosurePartState] = []
        for obj in self._scene.objects:
            if str(obj.get(TRANSACTION_ID_PROPERTY, "")) != transaction_id:
                continue
            center = tuple(float(value) * mm_per_unit for value in obj.location)
            dimensions = tuple(float(value) * mm_per_unit for value in obj.dimensions)
            states.append(
                EnclosurePartState(
                    enclosure_id=str(obj.get(ENCLOSURE_ID_PROPERTY, "")),
                    transaction_id=transaction_id,
                    part_id=str(obj.get(PART_ID_PROPERTY, "")),
                    part_type=str(obj.get(PART_TYPE_PROPERTY, "")),
                    shape=str(obj.get(SHAPE_PROPERTY, "")),
                    center_mm=center,  # type: ignore[arg-type]
                    dimensions_mm=dimensions,  # type: ignore[arg-type]
                    display_mode="wire" if obj.display_type == "WIRE" else "solid",
                )
            )
        return tuple(sorted(states, key=lambda item: item.part_id))

    def existing_state_matches(
        self, checkpoint: BlenderCreationCheckpoint, transaction_id: str
    ) -> bool:
        current = self._scene_port.read_snapshot().object_map()
        expected = {obj.object_id: obj for obj in checkpoint.object_states}
        if any(current.get(object_id) != state for object_id, state in expected.items()):
            return False
        for obj in self._scene.objects:
            object_id = stable_id(obj)
            if (
                object_id not in checkpoint.object_ids
                and str(obj.get(TRANSACTION_ID_PROPERTY, "")) != transaction_id
            ):
                return False
        return True

    def restore_creation_checkpoint(
        self, checkpoint: BlenderCreationCheckpoint, transaction_id: str
    ) -> bool:
        created_objects = [
            obj
            for obj in tuple(bpy.data.objects)
            if str(obj.get(TRANSACTION_ID_PROPERTY, "")) == transaction_id
        ]
        for obj in created_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in tuple(bpy.data.meshes):
            if (
                str(mesh.get(TRANSACTION_ID_PROPERTY, "")) == transaction_id
                and mesh.users == 0
            ):
                bpy.data.meshes.remove(mesh)
        for collection in tuple(bpy.data.collections):
            if str(collection.get(TRANSACTION_ID_PROPERTY, "")) == transaction_id:
                bpy.data.collections.remove(collection)
        try:
            transforms_restored = self._scene_port.restore_checkpoint(
                checkpoint.transforms
            )
        except (DomainError, RuntimeError, KeyError):
            return False
        bpy.context.view_layer.update()
        if not transforms_restored:
            return False
        current = self._scene_port.read_snapshot().object_map()
        expected = {obj.object_id: obj for obj in checkpoint.object_states}
        return set(current) == set(checkpoint.object_ids) and all(
            current.get(object_id) == state for object_id, state in expected.items()
        )
