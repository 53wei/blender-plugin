"""Blender-independent scene intermediate representation."""

from __future__ import annotations

from dataclasses import dataclass

Vector3 = tuple[float, float, float]
Matrix4 = tuple[float, ...]


@dataclass(frozen=True)
class BoundingBox:
    """World-space axis-aligned bounding box."""

    min_xyz: Vector3
    max_xyz: Vector3
    center: Vector3

    @classmethod
    def from_min_max(cls, min_xyz: Vector3, max_xyz: Vector3) -> "BoundingBox":
        """Build a validated box from its extrema."""
        if any(low > high for low, high in zip(min_xyz, max_xyz, strict=True)):
            raise ValueError("Bounding-box minimum must not exceed maximum")
        center = tuple((low + high) / 2.0 for low, high in zip(min_xyz, max_xyz, strict=True))
        return cls(min_xyz=min_xyz, max_xyz=max_xyz, center=center)  # type: ignore[arg-type]

    @property
    def dimensions(self) -> Vector3:
        """Return width, depth, and height."""
        return tuple(
            high - low for low, high in zip(self.min_xyz, self.max_xyz, strict=True)
        )  # type: ignore[return-value]

    def translated(self, delta: Vector3) -> "BoundingBox":
        """Return a copy shifted by a world-space delta."""
        minimum = tuple(value + shift for value, shift in zip(self.min_xyz, delta, strict=True))
        maximum = tuple(value + shift for value, shift in zip(self.max_xyz, delta, strict=True))
        return BoundingBox.from_min_max(minimum, maximum)  # type: ignore[arg-type]


@dataclass(frozen=True)
class ObjectState:
    """Read-only object state exposed to deterministic domain logic."""

    object_id: str
    name: str
    object_type: str
    matrix_world: Matrix4
    location_world: Vector3
    rotation_euler: Vector3
    scale: Vector3
    bbox_world: BoundingBox
    dimensions_world: Vector3
    parent_id: str | None
    locked: bool
    visible: bool


@dataclass(frozen=True)
class SceneSnapshot:
    """Immutable snapshot used by validation, execution, and verification."""

    schema_version: str
    snapshot_id: str
    scene_name: str
    unit_scale: float
    objects: tuple[ObjectState, ...]
    active_camera_id: str | None
    created_at: str
    fingerprint: str

    def object_map(self) -> dict[str, ObjectState]:
        """Index objects by stable ID and reject duplicate IDs."""
        indexed = {obj.object_id: obj for obj in self.objects}
        if len(indexed) != len(self.objects):
            raise ValueError("SceneSnapshot contains duplicate object IDs")
        return indexed

    def require_object(self, object_id: str) -> ObjectState:
        """Return an object or raise KeyError for the caller to map."""
        return self.object_map()[object_id]
