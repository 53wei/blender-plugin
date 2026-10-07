"""Shared deterministic scene and plan factories."""

from __future__ import annotations

from dataclasses import replace

from bsa.application.memory_scene import MemoryScenePort, translation_matrix
from bsa.core.fingerprint import fingerprint_snapshot
from bsa.core.validator import relevant_object_ids
from bsa.domain.actions import (
    ActionPlan,
    LockAction,
    PlaceOnAction,
    PreserveTransformConstraint,
)
from bsa.domain.scene import BoundingBox, ObjectState


def make_object(
    object_id: str,
    name: str,
    location: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    *,
    locked: bool = False,
) -> ObjectState:
    """Create an axis-aligned object state centered at location."""
    half = tuple(value / 2.0 for value in dimensions)
    minimum = tuple(value - size for value, size in zip(location, half, strict=True))
    maximum = tuple(value + size for value, size in zip(location, half, strict=True))
    return ObjectState(
        object_id=object_id,
        name=name,
        object_type="MESH",
        matrix_world=translation_matrix(location),
        location_world=location,
        rotation_euler=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        bbox_world=BoundingBox.from_min_max(minimum, maximum),  # type: ignore[arg-type]
        dimensions_world=dimensions,
        parent_id=None,
        locked=locked,
        visible=True,
    )


def make_scene() -> MemoryScenePort:
    """Create the standard Desk, Lamp, and Chair M1 fixture."""
    return MemoryScenePort(
        (
            make_object("desk-id", "Desk", (0.0, 0.0, 0.5), (4.0, 2.0, 1.0)),
            make_object("lamp-id", "Lamp", (0.0, 0.0, 0.5), (0.4, 0.4, 1.0)),
            make_object("chair-id", "Chair", (4.0, 0.0, 0.5), (1.0, 1.0, 1.0)),
        )
    )


def make_place_plan(
    scene: MemoryScenePort,
    *,
    region: str = "right",
    lock_target: bool = False,
    plan_id: str = "m1-demo-001",
) -> ActionPlan:
    """Build a previewed place_on plan against the scene's current fingerprint."""
    actions = [
        PlaceOnAction(
            action_id="place-1",
            object_id="lamp-id",
            target_id="desk-id",
            region=region,
            clearance=0.0,
        )
    ]
    if lock_target:
        actions.append(LockAction(action_id="lock-1", object_id="desk-id"))
    plan = ActionPlan(
        schema_version="0.1",
        plan_id=plan_id,
        source="test",
        scene_fingerprint="",
        requires_confirmation=False,
        actions=tuple(actions),
        constraints=(
            PreserveTransformConstraint(constraint_id="preserve-1", object_id="desk-id"),
        ),
        user_summary="Place Lamp on the right side of Desk and preserve Desk",
    )
    return replace(
        plan,
        scene_fingerprint=fingerprint_snapshot(scene.read_snapshot(), relevant_object_ids(plan)),
    )
