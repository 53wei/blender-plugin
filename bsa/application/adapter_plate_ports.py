"""隔离转接板创建事务与 Blender 的最小端口。"""

from __future__ import annotations

from typing import Any, Protocol

from ..domain.adapter_plate_mesh import AdapterPlateMeshSpec, AdapterPlateMeshState


class AdapterPlateCreationPort(Protocol):
    def plate_exists(self, plate_id: str) -> bool: ...

    def transaction_exists(self, transaction_id: str) -> bool: ...

    def capture_creation_checkpoint(self, transaction_id: str) -> Any: ...

    def create_adapter_plate(
        self,
        plate_id: str,
        transaction_id: str,
        spec: AdapterPlateMeshSpec,
    ) -> None: ...

    def read_created_plates(
        self, transaction_id: str
    ) -> tuple[AdapterPlateMeshState, ...]: ...

    def existing_state_matches(self, checkpoint: Any, transaction_id: str) -> bool: ...

    def restore_creation_checkpoint(self, checkpoint: Any, transaction_id: str) -> bool: ...
