"""用于快速测试外壳创建事务的内存端口。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..domain.enclosure_preview import EnclosurePartSpec, EnclosurePartState


@dataclass(frozen=True)
class MemoryCreationCheckpoint:
    existing_objects: dict[str, Any]
    created: dict[str, tuple[EnclosurePartState, ...]]


class MemoryEnclosurePreviewPort:
    """模拟创建、部分失败、篡改和完整回滚。"""

    def __init__(
        self,
        *,
        existing_objects: dict[str, Any] | None = None,
        fail_after_parts: int | None = None,
        tamper_part_id: str | None = None,
    ) -> None:
        self._existing_objects = dict(existing_objects or {})
        self._created: dict[str, tuple[EnclosurePartState, ...]] = {}
        self._fail_after_parts = fail_after_parts
        self._tamper_part_id = tamper_part_id
        self.checkpoint_count = 0

    @property
    def existing_objects(self) -> dict[str, Any]:
        return dict(self._existing_objects)

    def scene_state(
        self,
    ) -> tuple[
        tuple[tuple[str, Any], ...],
        tuple[tuple[str, tuple[EnclosurePartState, ...]], ...],
    ]:
        return (
            tuple(sorted(self._existing_objects.items())),
            tuple(sorted(self._created.items())),
        )

    def enclosure_exists(self, enclosure_id: str) -> bool:
        return any(
            part.enclosure_id == enclosure_id
            for parts in self._created.values()
            for part in parts
        )

    def transaction_exists(self, transaction_id: str) -> bool:
        return transaction_id in self._created

    def capture_creation_checkpoint(
        self, transaction_id: str
    ) -> MemoryCreationCheckpoint:
        del transaction_id
        self.checkpoint_count += 1
        return MemoryCreationCheckpoint(
            existing_objects=dict(self._existing_objects),
            created=dict(self._created),
        )

    def create_preview_parts(
        self,
        enclosure_id: str,
        transaction_id: str,
        parts: tuple[EnclosurePartSpec, ...],
    ) -> None:
        created: list[EnclosurePartState] = []
        self._created[transaction_id] = ()
        for part in parts:
            if self._fail_after_parts is not None and len(created) >= self._fail_after_parts:
                self._created[transaction_id] = tuple(created)
                raise RuntimeError("injected creation failure")
            state = EnclosurePartState(
                enclosure_id=enclosure_id,
                transaction_id=transaction_id,
                part_id=part.part_id,
                part_type=part.part_type,
                shape=part.shape,
                center_mm=part.center_mm,
                dimensions_mm=part.dimensions_mm,
                display_mode=part.display_mode,
            )
            if part.part_id == self._tamper_part_id:
                state = replace(
                    state,
                    dimensions_mm=(
                        state.dimensions_mm[0] + 1.0,
                        state.dimensions_mm[1],
                        state.dimensions_mm[2],
                    ),
                )
            created.append(state)
            self._created[transaction_id] = tuple(created)

    def read_created_parts(
        self, transaction_id: str
    ) -> tuple[EnclosurePartState, ...]:
        return self._created.get(transaction_id, ())

    def created_parts(self, transaction_id: str) -> tuple[EnclosurePartState, ...]:
        return self.read_created_parts(transaction_id)

    def existing_state_matches(
        self, checkpoint: MemoryCreationCheckpoint, transaction_id: str
    ) -> bool:
        other_created = {
            key: value for key, value in self._created.items() if key != transaction_id
        }
        return (
            self._existing_objects == checkpoint.existing_objects
            and other_created == checkpoint.created
        )

    def restore_creation_checkpoint(
        self, checkpoint: MemoryCreationCheckpoint, transaction_id: str
    ) -> bool:
        del transaction_id
        self._existing_objects = dict(checkpoint.existing_objects)
        self._created = dict(checkpoint.created)
        return self.scene_state() == (
            tuple(sorted(checkpoint.existing_objects.items())),
            tuple(sorted(checkpoint.created.items())),
        )
