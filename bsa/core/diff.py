"""Snapshot diff helpers used by verification and rollback checks."""

from __future__ import annotations

from ..domain.scene import ObjectState, SceneSnapshot


def max_matrix_delta(before: ObjectState, after: ObjectState) -> float:
    """Return the largest absolute world-matrix component change."""
    return max(
        abs(left - right)
        for left, right in zip(before.matrix_world, after.matrix_world, strict=True)
    )


def changed_transform_ids(
    before: SceneSnapshot, after: SceneSnapshot, *, tolerance: float
) -> tuple[str, ...]:
    """Return stable IDs whose transforms appeared, disappeared, or changed."""
    before_map = before.object_map()
    after_map = after.object_map()
    changed: list[str] = []
    for object_id in sorted(set(before_map) | set(after_map)):
        if object_id not in before_map or object_id not in after_map:
            changed.append(object_id)
        elif max_matrix_delta(before_map[object_id], after_map[object_id]) > tolerance:
            changed.append(object_id)
    return tuple(changed)
