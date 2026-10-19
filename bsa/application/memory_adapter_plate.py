"""用于快速验证转接板创建事务的内存端口。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..domain.adapter_plate_mesh import (
    AdapterPlateMeshSpec,
    AdapterPlateMeshState,
    MeasuredRoundHole,
)
from ..domain.adapter_plate import AdapterPlateDesign
from ..domain.errors import DomainError, ErrorCode


@dataclass(frozen=True)
class MemoryAdapterPlateCheckpoint:
    existing_objects: dict[str, Any]
    created: dict[str, tuple[AdapterPlateMeshState, ...]]
    designs: dict[str, AdapterPlateDesign]


class MemoryAdapterPlatePort:
    def __init__(
        self,
        *,
        existing_objects: dict[str, Any] | None = None,
        fail_on_create: bool = False,
        tamper: str | None = None,
    ) -> None:
        self._existing_objects = dict(existing_objects or {})
        self._created: dict[str, tuple[AdapterPlateMeshState, ...]] = {}
        self._designs: dict[str, AdapterPlateDesign] = {}
        self._fail_on_create = fail_on_create
        self._tamper = tamper
        self.update_tamper: str | None = None
        self.checkpoint_count = 0
        self.update_checkpoint_count = 0

    @property
    def existing_objects(self) -> dict[str, Any]:
        return dict(self._existing_objects)

    def scene_state(self) -> tuple[object, ...]:
        return (
            tuple(sorted(self._existing_objects.items())),
            tuple(sorted(self._created.items())),
            tuple(sorted(self._designs.items())),
        )

    def plate_exists(self, plate_id: str) -> bool:
        return any(
            state.plate_id == plate_id
            for states in self._created.values()
            for state in states
        )

    def transaction_exists(self, transaction_id: str) -> bool:
        return transaction_id in self._created

    def capture_creation_checkpoint(
        self, transaction_id: str
    ) -> MemoryAdapterPlateCheckpoint:
        del transaction_id
        self.checkpoint_count += 1
        return MemoryAdapterPlateCheckpoint(
            existing_objects=dict(self._existing_objects),
            created=dict(self._created),
            designs=dict(self._designs),
        )

    @staticmethod
    def _design(spec: AdapterPlateMeshSpec) -> AdapterPlateDesign:
        return AdapterPlateDesign(
            schema_version="0.1",
            plate_id=spec.plate_id,
            size_mm=spec.size_mm,
            corner_radius_mm=spec.corner_radius_mm,
            origin_offset_mm=spec.origin_offset_mm,
            holes=spec.holes,
        )

    @staticmethod
    def _state(
        plate_id: str,
        transaction_id: str,
        spec: AdapterPlateMeshSpec,
    ) -> AdapterPlateMeshState:
        return AdapterPlateMeshState(
            plate_id=plate_id,
            transaction_id=transaction_id,
            object_name=f"BSA_AdapterPlate_{plate_id}",
            size_mm=spec.size_mm,
            origin_offset_mm=spec.origin_offset_mm,
            corner_radius_mm=spec.corner_radius_mm,
            measured_holes=tuple(
                MeasuredRoundHole(hole.center_mm, hole.diameter_mm)
                for hole in spec.holes
            ),
            through_hole_count=len(spec.holes),
            is_manifold=True,
            connected_components=1,
            vertex_count=2
            * (
                4 * spec.outer_corner_segments
                + len(spec.holes) * spec.hole_segments
            ),
            face_count=1,
        )

    def create_adapter_plate(
        self,
        plate_id: str,
        transaction_id: str,
        spec: AdapterPlateMeshSpec,
    ) -> None:
        state = self._state(plate_id, transaction_id, spec)
        if self._tamper == "hole_diameter":
            state = replace(
                state,
                measured_holes=(
                    replace(state.measured_holes[0], diameter_mm=99.0),
                    *state.measured_holes[1:],
                ),
            )
        elif self._tamper == "manifold":
            state = replace(state, is_manifold=False)
        states = (state,)
        if self._tamper == "extra_object":
            states = (state, replace(state, object_name=f"{state.object_name}_extra"))
        self._created[transaction_id] = states
        self._designs[plate_id] = self._design(spec)
        if self._tamper == "existing_scene" and self._existing_objects:
            key = sorted(self._existing_objects)[0]
            self._existing_objects[key] = (999.0, 999.0, 999.0)
        if self._fail_on_create:
            raise RuntimeError("injected creation failure")

    def read_created_plates(
        self, transaction_id: str
    ) -> tuple[AdapterPlateMeshState, ...]:
        return self._created.get(transaction_id, ())

    def read_plate(self, plate_id: str) -> tuple[AdapterPlateMeshState, ...]:
        return tuple(
            state
            for states in self._created.values()
            for state in states
            if state.plate_id == plate_id
        )

    def read_plate_design(self, plate_id: str) -> AdapterPlateDesign:
        try:
            return self._designs[plate_id]
        except KeyError as error:
            raise DomainError(
                ErrorCode.OBJECT_NOT_FOUND,
                "要读取的转接板不存在",
                {"plate_id": plate_id},
            ) from error

    def capture_update_checkpoint(
        self,
        plate_id: str,
        transaction_id: str,
    ) -> MemoryAdapterPlateCheckpoint:
        del plate_id, transaction_id
        self.update_checkpoint_count += 1
        return MemoryAdapterPlateCheckpoint(
            existing_objects=dict(self._existing_objects),
            created=dict(self._created),
            designs=dict(self._designs),
        )

    def update_adapter_plate(
        self,
        plate_id: str,
        transaction_id: str,
        spec: AdapterPlateMeshSpec,
    ) -> None:
        for key, states in tuple(self._created.items()):
            remaining = tuple(state for state in states if state.plate_id != plate_id)
            if remaining:
                self._created[key] = remaining
            else:
                self._created.pop(key)
        state = self._state(plate_id, transaction_id, spec)
        if self.update_tamper == "hole_diameter":
            state = replace(
                state,
                measured_holes=(
                    replace(state.measured_holes[0], diameter_mm=99.0),
                    *state.measured_holes[1:],
                ),
            )
        self._created[transaction_id] = (state,)
        self._designs[plate_id] = self._design(spec)
        if self.update_tamper == "existing_scene" and self._existing_objects:
            key = sorted(self._existing_objects)[0]
            self._existing_objects[key] = (999.0, 999.0, 999.0)

    def existing_state_matches_update(
        self,
        checkpoint: MemoryAdapterPlateCheckpoint,
        plate_id: str,
        transaction_id: str,
    ) -> bool:
        del transaction_id

        def unrelated(
            created: dict[str, tuple[AdapterPlateMeshState, ...]],
        ) -> tuple[AdapterPlateMeshState, ...]:
            return tuple(
                state
                for states in created.values()
                for state in states
                if state.plate_id != plate_id
            )

        return (
            self._existing_objects == checkpoint.existing_objects
            and unrelated(self._created) == unrelated(checkpoint.created)
            and {
                key: value for key, value in self._designs.items() if key != plate_id
            }
            == {
                key: value
                for key, value in checkpoint.designs.items()
                if key != plate_id
            }
        )

    def commit_update_checkpoint(
        self,
        checkpoint: MemoryAdapterPlateCheckpoint,
        transaction_id: str,
    ) -> None:
        del checkpoint, transaction_id

    def restore_update_checkpoint(
        self,
        checkpoint: MemoryAdapterPlateCheckpoint,
        transaction_id: str,
    ) -> bool:
        del transaction_id
        self._existing_objects = dict(checkpoint.existing_objects)
        self._created = dict(checkpoint.created)
        self._designs = dict(checkpoint.designs)
        return self.scene_state() == (
            tuple(sorted(checkpoint.existing_objects.items())),
            tuple(sorted(checkpoint.created.items())),
            tuple(sorted(checkpoint.designs.items())),
        )

    def existing_state_matches(
        self,
        checkpoint: MemoryAdapterPlateCheckpoint,
        transaction_id: str,
    ) -> bool:
        other_created = {
            key: value for key, value in self._created.items() if key != transaction_id
        }
        return (
            self._existing_objects == checkpoint.existing_objects
            and other_created == checkpoint.created
        )

    def restore_creation_checkpoint(
        self,
        checkpoint: MemoryAdapterPlateCheckpoint,
        transaction_id: str,
    ) -> bool:
        del transaction_id
        self._existing_objects = dict(checkpoint.existing_objects)
        self._created = dict(checkpoint.created)
        self._designs = dict(checkpoint.designs)
        return self.scene_state() == (
            tuple(sorted(checkpoint.existing_objects.items())),
            tuple(sorted(checkpoint.created.items())),
            tuple(sorted(checkpoint.designs.items())),
        )
