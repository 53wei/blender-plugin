"""Pure world-space AABB placement calculations."""

from __future__ import annotations

import math

from ..domain.errors import DomainError, ErrorCode
from ..domain.scene import ObjectState, Vector3
from ..infra.config import MIN_CLEARANCE, POSITION_EPS


def _axis_center_range(
    target_min: float, target_max: float, object_size: float
) -> tuple[float, float]:
    half = object_size / 2.0
    return target_min + half + MIN_CLEARANCE, target_max - half - MIN_CLEARANCE


def _ensure_supported_surface(target: ObjectState) -> None:
    if abs(target.rotation_euler[0]) > POSITION_EPS or abs(target.rotation_euler[1]) > POSITION_EPS:
        raise DomainError(
            ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
            "M1 only supports horizontal AABB target surfaces",
            {"target_id": target.object_id, "rotation_euler": target.rotation_euler},
        )


def place_on_location(
    source: ObjectState, target: ObjectState, *, region: str, clearance: float
) -> Vector3:
    """Calculate a source origin that places its AABB on a target top face."""
    _ensure_supported_surface(target)
    width, depth, _height = source.dimensions_world
    x_min, x_max = _axis_center_range(
        target.bbox_world.min_xyz[0], target.bbox_world.max_xyz[0], width
    )
    y_min, y_max = _axis_center_range(
        target.bbox_world.min_xyz[1], target.bbox_world.max_xyz[1], depth
    )
    if x_min > x_max or y_min > y_max:
        raise DomainError(
            ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
            "Source footprint does not fit on the target AABB",
            {"object_id": source.object_id, "target_id": target.object_id},
        )

    x = min(max(source.bbox_world.center[0], x_min), x_max)
    y = min(max(source.bbox_world.center[1], y_min), y_max)
    if region == "left":
        x = x_min
    elif region == "right":
        x = x_max
    elif region == "front":
        y = y_min
    elif region == "back":
        y = y_max
    elif region == "center":
        x = (x_min + x_max) / 2.0
        y = (y_min + y_max) / 2.0
    else:
        raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Unknown place_on region")

    delta_x = x - source.bbox_world.center[0]
    delta_y = y - source.bbox_world.center[1]
    delta_z = target.bbox_world.max_xyz[2] + clearance - source.bbox_world.min_xyz[2]
    return (
        source.location_world[0] + delta_x,
        source.location_world[1] + delta_y,
        source.location_world[2] + delta_z,
    )


def relative_place_location(
    source: ObjectState, target: ObjectState, *, relation: str, distance: float
) -> Vector3:
    """Place one AABB outside another at an explicit world-axis gap."""
    if not math.isfinite(distance) or distance < 0.0:
        raise DomainError(
            ErrorCode.PRECONDITION_FAILED, "Relative placement distance must be non-negative"
        )
    x, y, z = source.location_world
    if relation == "right_of":
        delta = target.bbox_world.max_xyz[0] + distance - source.bbox_world.min_xyz[0]
        x += delta
    elif relation == "left_of":
        delta = target.bbox_world.min_xyz[0] - distance - source.bbox_world.max_xyz[0]
        x += delta
    elif relation == "front_of":
        delta = target.bbox_world.min_xyz[1] - distance - source.bbox_world.max_xyz[1]
        y += delta
    elif relation == "back_of":
        delta = target.bbox_world.max_xyz[1] + distance - source.bbox_world.min_xyz[1]
        y += delta
    else:
        raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Unknown relative relation")
    return (x, y, z)
