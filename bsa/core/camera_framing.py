"""Deterministic AABB-based camera framing for the guided workflow."""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import uuid4

from ..domain.errors import DomainError, ErrorCode
from ..domain.scene import BoundingBox, SceneSnapshot, Vector3
from .fingerprint import fingerprint_snapshot


@dataclass(frozen=True)
class CameraFramePlan:
    """Previewable camera transform derived only from scene state and settings."""

    schema_version: str
    plan_id: str
    scene_fingerprint: str
    object_ids: tuple[str, ...]
    target: Vector3
    camera_location: Vector3
    lens_mm: float
    sensor_width_mm: float
    margin: float
    clip_start: float
    clip_end: float

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "scene_fingerprint": self.scene_fingerprint,
            "object_ids": list(self.object_ids),
            "target": list(self.target),
            "camera_location": list(self.camera_location),
            "lens_mm": self.lens_mm,
            "sensor_width_mm": self.sensor_width_mm,
            "margin": self.margin,
            "clip_start": self.clip_start,
            "clip_end": self.clip_end,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> CameraFramePlan:
        required = {
            "schema_version",
            "plan_id",
            "scene_fingerprint",
            "object_ids",
            "target",
            "camera_location",
            "lens_mm",
            "sensor_width_mm",
            "margin",
            "clip_start",
            "clip_end",
        }
        if set(payload) != required or payload.get("schema_version") != "0.1":
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Invalid camera frame plan")
        object_ids = payload["object_ids"]
        target = payload["target"]
        location = payload["camera_location"]
        if (
            not isinstance(object_ids, list)
            or not object_ids
            or not all(isinstance(item, str) and item for item in object_ids)
            or len(set(object_ids)) != len(object_ids)
            or not isinstance(target, list)
            or len(target) != 3
            or not isinstance(location, list)
            or len(location) != 3
        ):
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Invalid camera frame vectors")

        def finite(value: object, field: str) -> float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, f"{field} must be finite")
            number = float(value)
            if not math.isfinite(number):
                raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, f"{field} must be finite")
            return number

        plan_id = payload["plan_id"]
        scene_fingerprint = payload["scene_fingerprint"]
        if not isinstance(plan_id, str) or not plan_id:
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Camera plan ID is invalid")
        if not isinstance(scene_fingerprint, str) or not scene_fingerprint:
            raise DomainError(
                ErrorCode.PLAN_SCHEMA_INVALID,
                "Camera scene fingerprint is invalid",
            )
        parsed = cls(
            schema_version="0.1",
            plan_id=plan_id,
            scene_fingerprint=scene_fingerprint,
            object_ids=tuple(object_ids),
            target=tuple(finite(value, "target") for value in target),  # type: ignore[arg-type]
            camera_location=tuple(
                finite(value, "camera_location") for value in location
            ),  # type: ignore[arg-type]
            lens_mm=finite(payload["lens_mm"], "lens_mm"),
            sensor_width_mm=finite(payload["sensor_width_mm"], "sensor_width_mm"),
            margin=finite(payload["margin"], "margin"),
            clip_start=finite(payload["clip_start"], "clip_start"),
            clip_end=finite(payload["clip_end"], "clip_end"),
        )
        if not 10.0 <= parsed.lens_mm <= 200.0:
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Camera lens is out of range")
        if parsed.sensor_width_mm <= 0.0 or not 0.0 <= parsed.margin <= 0.5:
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Camera framing is out of range")
        if parsed.clip_start <= 0.0 or parsed.clip_end <= parsed.clip_start:
            raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "Camera clipping is invalid")
        return parsed


def bounds_for_objects(snapshot: SceneSnapshot, object_ids: tuple[str, ...]) -> BoundingBox:
    """Return the union AABB for an explicit non-empty object set."""

    requested = tuple(dict.fromkeys(object_ids))
    if not requested:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Select objects to frame")
    indexed = snapshot.object_map()
    missing = [object_id for object_id in requested if object_id not in indexed]
    if missing:
        raise DomainError(
            ErrorCode.OBJECT_NOT_FOUND,
            "Camera plan references missing objects",
            {"object_ids": missing},
        )
    objects = [indexed[object_id] for object_id in requested]
    minimum = tuple(min(obj.bbox_world.min_xyz[axis] for obj in objects) for axis in range(3))
    maximum = tuple(max(obj.bbox_world.max_xyz[axis] for obj in objects) for axis in range(3))
    return BoundingBox.from_min_max(minimum, maximum)  # type: ignore[arg-type]


def build_camera_frame_plan(
    snapshot: SceneSnapshot,
    object_ids: tuple[str, ...],
    *,
    lens_mm: float,
    aspect_ratio: float,
    margin: float,
    sensor_width_mm: float = 36.0,
    view_direction: Vector3 = (1.0, -1.0, 0.75),
) -> CameraFramePlan:
    """Fit a bounding sphere inside both horizontal and vertical perspective FOV."""

    if not 10.0 <= lens_mm <= 200.0:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Lens must be between 10 and 200 mm")
    if not 0.0 <= margin <= 0.5:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Camera margin must be 0 to 0.5")
    if not math.isfinite(aspect_ratio) or not 0.1 <= aspect_ratio <= 10.0:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Render aspect ratio is invalid")
    if not math.isfinite(sensor_width_mm) or sensor_width_mm <= 0.0:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Sensor width must be positive")
    if not all(math.isfinite(value) for value in view_direction):
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Camera direction must be finite")
    direction_length = math.sqrt(sum(value * value for value in view_direction))
    if direction_length <= 1e-9:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Camera direction cannot be zero")

    object_ids = tuple(dict.fromkeys(object_ids))
    bounds = bounds_for_objects(snapshot, object_ids)
    half_dimensions = tuple(value / 2.0 for value in bounds.dimensions)
    radius = max(0.01, math.sqrt(sum(value * value for value in half_dimensions)))
    sensor_height_mm = sensor_width_mm / aspect_ratio
    horizontal_half_fov = math.atan(sensor_width_mm / (2.0 * lens_mm))
    vertical_half_fov = math.atan(sensor_height_mm / (2.0 * lens_mm))
    limiting_half_fov = min(horizontal_half_fov, vertical_half_fov)
    usable_sine = math.sin(limiting_half_fov) * (1.0 - margin)
    distance = radius / max(usable_sine, 1e-6)
    direction = tuple(value / direction_length for value in view_direction)
    location = tuple(
        center + unit * distance
        for center, unit in zip(bounds.center, direction, strict=True)
    )
    clip_start = max(0.001, min(0.1, distance - radius * 1.5))
    clip_end = max(100.0, distance + radius * 4.0)
    return CameraFramePlan(
        schema_version="0.1",
        plan_id=str(uuid4()),
        scene_fingerprint=fingerprint_snapshot(snapshot, object_ids),
        object_ids=object_ids,
        target=bounds.center,
        camera_location=location,  # type: ignore[arg-type]
        lens_mm=float(lens_mm),
        sensor_width_mm=float(sensor_width_mm),
        margin=float(margin),
        clip_start=clip_start,
        clip_end=clip_end,
    )


def validate_camera_plan_current(plan: CameraFramePlan, snapshot: SceneSnapshot) -> None:
    """Reject a camera preview after any framed object changed."""

    current = fingerprint_snapshot(snapshot, plan.object_ids)
    if current != plan.scene_fingerprint:
        raise DomainError(
            ErrorCode.PLAN_STALE,
            "Scene changed after camera preview; generate a new preview",
        )


def describe_camera_plan(plan: CameraFramePlan, snapshot: SceneSnapshot) -> str:
    names = snapshot.object_map()
    display = "、".join(names[object_id].name for object_id in plan.object_ids)
    x, y, z = plan.camera_location
    return (
        f"取景对象：{display}\n"
        f"镜头：{plan.lens_mm:g} mm；画面留白：{plan.margin * 100:g}%\n"
        f"相机位置：({x:.3f}, {y:.3f}, {z:.3f})\n"
        "确认后才会创建或移动场景相机"
    )
