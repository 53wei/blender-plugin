"""Build confirmable local plans for the three-step guided workflow."""

from __future__ import annotations

import math
from dataclasses import replace
from uuid import uuid4

from ..core.fingerprint import fingerprint_snapshot
from ..core.layout import align_deltas, grid_deltas, ground_deltas
from ..core.validator import PlanValidator, relevant_object_ids
from ..domain.actions import (
    ActionPlan,
    MoveAction,
    PreserveTransformConstraint,
    RotateAction,
    ScaleUniformAction,
)
from ..domain.errors import DomainError, ErrorCode
from ..domain.scene import SceneSnapshot, Vector3
from ..infra.config import POSITION_EPS


def _nonzero_moves(
    deltas: dict[str, Vector3],
    *,
    prefix: str,
) -> tuple[MoveAction, ...]:
    return tuple(
        MoveAction(
            action_id=f"{prefix}-{index}",
            object_id=object_id,
            delta=delta,
        )
        for index, (object_id, delta) in enumerate(sorted(deltas.items()), 1)
        if max(abs(value) for value in delta) > POSITION_EPS
    )


def _finish_plan(
    snapshot: SceneSnapshot,
    *,
    actions: tuple[object, ...],
    summary: str,
    constraints: tuple[PreserveTransformConstraint, ...] = (),
) -> ActionPlan:
    if not actions:
        raise DomainError(
            ErrorCode.PRECONDITION_FAILED,
            "The selected objects already satisfy this operation",
        )
    plan = ActionPlan(
        schema_version="0.1",
        plan_id=str(uuid4()),
        source="ui",
        scene_fingerprint="",
        requires_confirmation=True,
        actions=actions,  # type: ignore[arg-type]
        constraints=constraints,
        user_summary=summary,
    )
    plan = replace(
        plan,
        scene_fingerprint=fingerprint_snapshot(snapshot, relevant_object_ids(plan)),
    )
    PlanValidator().validate(plan, snapshot)
    return plan


class GuidedWorkflowPlanBuilder:
    """Create local, inspectable plans without calling an AI provider."""

    def ground(
        self,
        snapshot: SceneSnapshot,
        object_ids: tuple[str, ...],
        *,
        ground_z: float = 0.0,
    ) -> ActionPlan:
        deltas = ground_deltas(snapshot.objects, object_ids, ground_z=ground_z)
        return _finish_plan(
            snapshot,
            actions=_nonzero_moves(deltas, prefix="ground"),
            summary=f"将 {len(object_ids)} 个所选物体落到地面",
        )

    def align(
        self,
        snapshot: SceneSnapshot,
        object_ids: tuple[str, ...],
        *,
        reference_id: str,
        axis: str,
        anchor: str,
    ) -> ActionPlan:
        deltas = align_deltas(
            snapshot.objects,
            object_ids,
            reference_id=reference_id,
            axis=axis,
            anchor=anchor,
        )
        return _finish_plan(
            snapshot,
            actions=_nonzero_moves(deltas, prefix="align"),
            constraints=(
                PreserveTransformConstraint(
                    constraint_id="preserve-reference",
                    object_id=reference_id,
                ),
            ),
            summary=f"按活动物体在 {axis.upper()} 轴对齐所选物体",
        )

    def grid(
        self,
        snapshot: SceneSnapshot,
        object_ids: tuple[str, ...],
        *,
        columns: int,
        gap: float,
    ) -> ActionPlan:
        deltas = grid_deltas(
            snapshot.objects,
            object_ids,
            columns=columns,
            gap=gap,
        )
        return _finish_plan(
            snapshot,
            actions=_nonzero_moves(deltas, prefix="grid"),
            summary=f"将 {len(object_ids)} 个所选物体排列成 {columns} 列网格",
        )

    def rotate(
        self,
        snapshot: SceneSnapshot,
        object_ids: tuple[str, ...],
        *,
        axis: str,
        angle_degrees: float,
    ) -> ActionPlan:
        if not math.isfinite(angle_degrees) or abs(angle_degrees) <= POSITION_EPS:
            raise DomainError(
                ErrorCode.PRECONDITION_FAILED,
                "Rotation angle must be a non-zero finite number",
            )
        actions = tuple(
            RotateAction(
                action_id=f"rotate-{index}",
                object_id=object_id,
                axis=axis,
                angle_radians=math.radians(angle_degrees),
            )
            for index, object_id in enumerate(dict.fromkeys(object_ids), 1)
        )
        return _finish_plan(
            snapshot,
            actions=actions,
            summary=(
                f"将 {len(actions)} 个所选物体绕 {axis.upper()} 轴"
                f"旋转 {angle_degrees:g}°"
            ),
        )

    def scale(
        self,
        snapshot: SceneSnapshot,
        object_ids: tuple[str, ...],
        *,
        factor: float,
    ) -> ActionPlan:
        if not math.isfinite(factor) or abs(factor - 1.0) <= POSITION_EPS:
            raise DomainError(
                ErrorCode.PRECONDITION_FAILED,
                "Scale factor must be finite and different from 1",
            )
        actions = tuple(
            ScaleUniformAction(
                action_id=f"scale-{index}",
                object_id=object_id,
                factor=factor,
            )
            for index, object_id in enumerate(dict.fromkeys(object_ids), 1)
        )
        return _finish_plan(
            snapshot,
            actions=actions,
            summary=f"将 {len(actions)} 个所选物体等比缩放 {factor:g} 倍",
        )
