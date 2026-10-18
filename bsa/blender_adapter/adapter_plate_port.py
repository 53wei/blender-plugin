"""Blender 4.5 转接板真实网格创建器、回读器与创建型检查点。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import bmesh
import bpy
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

from .ids import ensure_stable_ids, stable_id
from .scene_port import BlenderObjectCheckpoint, BlenderScenePort
from ..domain.adapter_plate_mesh import (
    AdapterPlateMeshSpec,
    AdapterPlateMeshState,
    MeasuredRoundHole,
)
from ..domain.errors import DomainError, ErrorCode
from ..domain.scene import ObjectState

PLATE_ID_PROPERTY = "bsa_adapter_plate_id"
TRANSACTION_ID_PROPERTY = "bsa_creation_transaction_id"
PLATE_ROLE_PROPERTY = "bsa_adapter_plate_role"


@dataclass(frozen=True)
class BlenderAdapterPlateCheckpoint:
    object_ids: tuple[str, ...]
    object_states: tuple[ObjectState, ...]
    transforms: dict[str, BlenderObjectCheckpoint]


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.")
    return cleaned[:48] or "adapter_plate"


def _rounded_rectangle(
    width: float,
    depth: float,
    radius: float,
    segments: int,
) -> list[tuple[float, float]]:
    if radius == 0.0:
        return [(0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)]
    corners = (
        (width - radius, radius, -math.pi / 2.0),
        (width - radius, depth - radius, 0.0),
        (radius, depth - radius, math.pi / 2.0),
        (radius, radius, math.pi),
    )
    points = [
        (
            center_x + radius * math.cos(start + step * math.pi / (2.0 * segments)),
            center_y + radius * math.sin(start + step * math.pi / (2.0 * segments)),
        )
        for center_x, center_y, start in corners
        for step in range(segments + 1)
    ]
    deduplicated: list[tuple[float, float]] = []
    for point in points:
        if not deduplicated or math.dist(point, deduplicated[-1]) > 1e-12:
            deduplicated.append(point)
    if len(deduplicated) > 1 and math.dist(deduplicated[0], deduplicated[-1]) <= 1e-12:
        deduplicated.pop()
    return deduplicated


def _clockwise_circle(
    center: tuple[float, float],
    radius: float,
    segments: int,
) -> list[tuple[float, float]]:
    return [
        (
            center[0] + radius * math.cos(-2.0 * math.pi * index / segments),
            center[1] + radius * math.sin(-2.0 * math.pi * index / segments),
        )
        for index in range(segments)
    ]


def _plate_geometry(
    spec: AdapterPlateMeshSpec,
    mm_per_unit: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    width, depth, thickness = (value / mm_per_unit for value in spec.size_mm)
    radius = spec.corner_radius_mm / mm_per_unit
    contours = [
        _rounded_rectangle(
            width,
            depth,
            radius,
            spec.outer_corner_segments,
        )
    ]
    contours.extend(
        _clockwise_circle(
            (
                hole.center_mm[0] / mm_per_unit,
                hole.center_mm[1] / mm_per_unit,
            ),
            hole.diameter_mm / (2.0 * mm_per_unit),
            spec.hole_segments,
        )
        for hole in spec.holes
    )
    flat = [point for contour in contours for point in contour]
    vectors = [Vector((x, y, 0.0)) for x, y in flat]
    vector_contours: list[list[Vector]] = []
    cursor = 0
    for contour in contours:
        vector_contours.append(vectors[cursor : cursor + len(contour)])
        cursor += len(contour)
    triangles = tessellate_polygon(vector_contours)
    if not triangles:
        raise DomainError(
            ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
            "转接板二维轮廓无法可靠三角剖分",
        )

    count = len(flat)
    vertices = [(x, y, 0.0) for x, y in flat] + [
        (x, y, thickness) for x, y in flat
    ]
    faces: list[tuple[int, ...]] = []
    faces.extend(tuple(reversed(triangle)) for triangle in triangles)
    faces.extend(tuple(index + count for index in triangle) for triangle in triangles)
    offset = 0
    for contour in contours:
        contour_count = len(contour)
        for index in range(contour_count):
            following = (index + 1) % contour_count
            faces.append(
                (
                    offset + index,
                    offset + following,
                    count + offset + following,
                    count + offset + index,
                )
            )
        offset += contour_count
    return vertices, faces


def _connected_components(adjacency: dict[int, set[int]], count: int) -> int:
    unseen = set(range(count))
    components = 0
    while unseen:
        components += 1
        pending = [unseen.pop()]
        while pending:
            current = pending.pop()
            for neighbor in adjacency.get(current, set()):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    pending.append(neighbor)
    return components


def _xy_components_from_vertical_sides(
    mesh: object,
    coordinates_mm: list[tuple[float, float, float]],
) -> list[list[tuple[float, float]]]:
    z_values = [coordinate[2] for coordinate in coordinates_mm]
    z_min = min(z_values)
    z_max = max(z_values)
    tolerance = 1e-5
    adjacency: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for polygon in mesh.polygons:
        heights = [coordinates_mm[index][2] for index in polygon.vertices]
        if min(heights) > z_min + tolerance or max(heights) < z_max - tolerance:
            continue
        points = {
            (
                round(coordinates_mm[index][0], 8),
                round(coordinates_mm[index][1], 8),
            )
            for index in polygon.vertices
        }
        if len(points) != 2:
            continue
        left, right = tuple(points)
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    unseen = set(adjacency)
    components: list[list[tuple[float, float]]] = []
    while unseen:
        start = unseen.pop()
        pending = [start]
        component = [start]
        while pending:
            current = pending.pop()
            for neighbor in adjacency[current]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    pending.append(neighbor)
                    component.append(neighbor)
        components.append(component)
    return components


def _measure_mesh_state(
    obj: object,
    *,
    mm_per_unit: float,
    plate_id: str,
    transaction_id: str,
) -> AdapterPlateMeshState:
    mesh = obj.data
    coordinates = [
        tuple(float(value) * mm_per_unit for value in vertex.co)
        for vertex in mesh.vertices
    ]
    minimum = tuple(min(point[axis] for point in coordinates) for axis in range(3))
    maximum = tuple(max(point[axis] for point in coordinates) for axis in range(3))
    size = tuple(maximum[axis] - minimum[axis] for axis in range(3))

    adjacency: dict[int, set[int]] = {}
    for edge in mesh.edges:
        left, right = edge.vertices
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    connected = _connected_components(adjacency, len(mesh.vertices))
    bm = bmesh.new()
    bm.from_mesh(mesh)
    manifold = bool(bm.edges) and all(edge.is_manifold for edge in bm.edges)
    bm.free()

    contour_components = _xy_components_from_vertical_sides(mesh, coordinates)
    if not contour_components:
        outer: list[tuple[float, float]] = []
        holes: list[list[tuple[float, float]]] = []
    else:
        outer = max(
            contour_components,
            key=lambda points: (
                max(point[0] for point in points) - min(point[0] for point in points)
            )
            * (
                max(point[1] for point in points) - min(point[1] for point in points)
            ),
        )
        holes = [points for points in contour_components if points is not outer]

    corner_radius = 0.0
    if outer:
        outer_min_x = min(point[0] for point in outer)
        outer_min_y = min(point[1] for point in outer)
        bottom_x = [
            point[0]
            for point in outer
            if abs(point[1] - outer_min_y) <= 1e-5
        ]
        if bottom_x:
            corner_radius = max(0.0, min(bottom_x) - outer_min_x)
    measured_holes = tuple(
        sorted(
            (
                MeasuredRoundHole(
                    center_mm=(
                        (min(point[0] for point in points) + max(point[0] for point in points))
                        / 2.0,
                        (min(point[1] for point in points) + max(point[1] for point in points))
                        / 2.0,
                    ),
                    diameter_mm=(
                        max(point[0] for point in points)
                        - min(point[0] for point in points)
                        + max(point[1] for point in points)
                        - min(point[1] for point in points)
                    )
                    / 2.0,
                )
                for points in holes
            ),
            key=lambda hole: hole.center_mm,
        )
    )
    origin = tuple(float(value) * mm_per_unit for value in obj.location)
    return AdapterPlateMeshState(
        plate_id=plate_id,
        transaction_id=transaction_id,
        object_name=obj.name,
        size_mm=size,  # type: ignore[arg-type]
        origin_offset_mm=origin,  # type: ignore[arg-type]
        corner_radius_mm=corner_radius,
        measured_holes=measured_holes,
        through_hole_count=len(holes),
        is_manifold=manifold,
        connected_components=connected,
        vertex_count=len(mesh.vertices),
        face_count=len(mesh.polygons),
    )


class BlenderAdapterPlatePort:
    """只通过严格网格规格创建并回读单一转接板对象。"""

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

    def plate_exists(self, plate_id: str) -> bool:
        return any(
            str(obj.get(PLATE_ID_PROPERTY, "")) == plate_id
            for obj in self._scene.objects
        ) or any(
            str(collection.get(PLATE_ID_PROPERTY, "")) == plate_id
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
        self,
        transaction_id: str,
    ) -> BlenderAdapterPlateCheckpoint:
        del transaction_id
        snapshot = self._scene_port.read_snapshot()
        object_ids = tuple(sorted(obj.object_id for obj in snapshot.objects))
        return BlenderAdapterPlateCheckpoint(
            object_ids=object_ids,
            object_states=snapshot.objects,
            transforms=self._scene_port.capture_checkpoint(object_ids),
        )

    def create_adapter_plate(
        self,
        plate_id: str,
        transaction_id: str,
        spec: AdapterPlateMeshSpec,
    ) -> None:
        mm_per_unit = self._millimetres_per_blender_unit()
        vertices, faces = _plate_geometry(spec, mm_per_unit)
        collection = bpy.data.collections.new(
            f"BSA_AdapterPlate_{_safe_name(plate_id)}"
        )
        collection[PLATE_ID_PROPERTY] = plate_id
        collection[TRANSACTION_ID_PROPERTY] = transaction_id
        self._scene.collection.children.link(collection)

        object_name = f"BSA_AdapterPlate_{_safe_name(plate_id)}"
        mesh = bpy.data.meshes.new(f"{object_name}_Mesh")
        mesh[TRANSACTION_ID_PROPERTY] = transaction_id
        mesh.from_pydata(vertices, [], faces)
        mesh.validate(clean_customdata=False)
        mesh.update(calc_edges=True)
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(mesh)
        bm.free()
        mesh.update(calc_edges=True)

        obj = bpy.data.objects.new(object_name, mesh)
        obj[PLATE_ID_PROPERTY] = plate_id
        obj[TRANSACTION_ID_PROPERTY] = transaction_id
        obj[PLATE_ROLE_PROPERTY] = "adapter_plate"
        collection.objects.link(obj)
        obj.location = tuple(
            value / mm_per_unit for value in spec.origin_offset_mm
        )
        obj.color = (0.12, 0.38, 0.82, 1.0)
        ensure_stable_ids(collection.objects)
        bpy.context.view_layer.update()

    def read_created_plates(
        self,
        transaction_id: str,
    ) -> tuple[AdapterPlateMeshState, ...]:
        mm_per_unit = self._millimetres_per_blender_unit()
        bpy.context.view_layer.update()
        states = []
        for obj in self._scene.objects:
            if str(obj.get(TRANSACTION_ID_PROPERTY, "")) != transaction_id:
                continue
            if obj.type != "MESH":
                states.append(
                    AdapterPlateMeshState(
                        plate_id=str(obj.get(PLATE_ID_PROPERTY, "")),
                        transaction_id=transaction_id,
                        object_name=obj.name,
                        size_mm=(0.0, 0.0, 0.0),
                        origin_offset_mm=(0.0, 0.0, 0.0),
                        corner_radius_mm=0.0,
                        measured_holes=(),
                        through_hole_count=0,
                        is_manifold=False,
                        connected_components=0,
                        vertex_count=0,
                        face_count=0,
                    )
                )
                continue
            states.append(
                _measure_mesh_state(
                    obj,
                    mm_per_unit=mm_per_unit,
                    plate_id=str(obj.get(PLATE_ID_PROPERTY, "")),
                    transaction_id=transaction_id,
                )
            )
        return tuple(sorted(states, key=lambda state: state.object_name))

    def existing_state_matches(
        self,
        checkpoint: BlenderAdapterPlateCheckpoint,
        transaction_id: str,
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
        self,
        checkpoint: BlenderAdapterPlateCheckpoint,
        transaction_id: str,
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
            restored = self._scene_port.restore_checkpoint(checkpoint.transforms)
        except (DomainError, RuntimeError, KeyError):
            return False
        bpy.context.view_layer.update()
        if not restored:
            return False
        current = self._scene_port.read_snapshot().object_map()
        expected = {obj.object_id: obj for obj in checkpoint.object_states}
        return set(current) == set(checkpoint.object_ids) and all(
            current.get(object_id) == state for object_id, state in expected.items()
        )
