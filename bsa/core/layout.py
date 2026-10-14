"""Pure layout calculations used by the guided scene workflow."""

from __future__ import annotations

import math
from collections.abc import Iterable

from ..domain.errors import DomainError, ErrorCode
from ..domain.scene import ObjectState, Vector3
from ..infra.config import POSITION_EPS

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _objects_by_id(
    objects: Iterable[ObjectState], object_ids: Iterable[str]
) -> tuple[ObjectState, ...]:
    indexed = {obj.object_id: obj for obj in objects}
    requested = tuple(dict.fromkeys(object_ids))
    if not requested:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Select at least one object")
    missing = [object_id for object_id in requested if object_id not in indexed]
    if missing:
        raise DomainError(
            ErrorCode.OBJECT_NOT_FOUND,
            "Layout references an object that is not in the scene",
            {"object_ids": missing},
        )
    return tuple(indexed[object_id] for object_id in requested)


def ground_deltas(
    objects: Iterable[ObjectState],
    object_ids: Iterable[str],
    *,
    ground_z: float = 0.0,
) -> dict[str, Vector3]:
    """Return vertical moves that put every selected AABB on a ground plane."""

    if not math.isfinite(ground_z):
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Ground height must be finite")
    result: dict[str, Vector3] = {}
    for obj in _objects_by_id(objects, object_ids):
        delta_z = ground_z - obj.bbox_world.min_xyz[2]
        if abs(delta_z) > POSITION_EPS:
            result[obj.object_id] = (0.0, 0.0, delta_z)
    return result


def align_deltas(
    objects: Iterable[ObjectState],
    object_ids: Iterable[str],
    *,
    reference_id: str,
    axis: str,
    anchor: str,
) -> dict[str, Vector3]:
    """Align selected AABB edges or centers to one explicit reference object."""

    if axis not in _AXIS_INDEX:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Alignment axis must be x, y, or z")
    if anchor not in {"min", "center", "max"}:
        raise DomainError(
            ErrorCode.PRECONDITION_FAILED,
            "Alignment anchor must be min, center, or max",
        )
    selected = _objects_by_id(objects, object_ids)
    if len(selected) < 2:
        raise DomainError(
            ErrorCode.PRECONDITION_FAILED,
            "Alignment needs at least two selected objects",
        )
    indexed = {obj.object_id: obj for obj in selected}
    if reference_id not in indexed:
        raise DomainError(
            ErrorCode.PRECONDITION_FAILED,
            "The active reference must be part of the selection",
        )
    axis_index = _AXIS_INDEX[axis]

    def anchor_value(obj: ObjectState) -> float:
        if anchor == "min":
            return obj.bbox_world.min_xyz[axis_index]
        if anchor == "max":
            return obj.bbox_world.max_xyz[axis_index]
        return obj.bbox_world.center[axis_index]

    target = anchor_value(indexed[reference_id])
    result: dict[str, Vector3] = {}
    for obj in selected:
        if obj.object_id == reference_id:
            continue
        shift = target - anchor_value(obj)
        if abs(shift) <= POSITION_EPS:
            continue
        delta = [0.0, 0.0, 0.0]
        delta[axis_index] = shift
        result[obj.object_id] = tuple(delta)  # type: ignore[assignment]
    return result


def grid_deltas(
    objects: Iterable[ObjectState],
    object_ids: Iterable[str],
    *,
    columns: int,
    gap: float,
) -> dict[str, Vector3]:
    """Arrange selected objects in a deterministic centered XY grid."""

    selected = _objects_by_id(objects, object_ids)
    if len(selected) < 2:
        raise DomainError(
            ErrorCode.PRECONDITION_FAILED,
            "Grid arrangement needs at least two selected objects",
        )
    if isinstance(columns, bool) or not isinstance(columns, int) or columns < 1:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Grid columns must be positive")
    if not math.isfinite(gap) or gap < 0.0:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Grid gap must be non-negative")

    ordered = tuple(sorted(selected, key=lambda obj: (obj.name.casefold(), obj.object_id)))
    columns = min(columns, len(ordered))
    rows = math.ceil(len(ordered) / columns)
    cell_width = max(obj.dimensions_world[0] for obj in ordered) + gap
    cell_depth = max(obj.dimensions_world[1] for obj in ordered) + gap
    center_x = (min(obj.bbox_world.min_xyz[0] for obj in ordered) + max(
        obj.bbox_world.max_xyz[0] for obj in ordered
    )) / 2.0
    center_y = (min(obj.bbox_world.min_xyz[1] for obj in ordered) + max(
        obj.bbox_world.max_xyz[1] for obj in ordered
    )) / 2.0

    result: dict[str, Vector3] = {}
    for index, obj in enumerate(ordered):
        row, column = divmod(index, columns)
        row_size = min(columns, len(ordered) - row * columns)
        target_x = center_x + (column - (row_size - 1) / 2.0) * cell_width
        target_y = center_y + ((rows - 1) / 2.0 - row) * cell_depth
        delta = (
            target_x - obj.bbox_world.center[0],
            target_y - obj.bbox_world.center[1],
            0.0,
        )
        if max(abs(value) for value in delta) > POSITION_EPS:
            result[obj.object_id] = delta
    return result
