"""隔离转接板创建事务与 Blender 的最小端口。"""

from __future__ import annotations

from typing import Any, Protocol

from ..domain.adapter_plate import AdapterPlateDesign
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


class AdapterPlateUpdatePort(Protocol):
    """读取、更新和恢复单个已管理转接板的最小端口。"""

    def plate_exists(self, plate_id: str) -> bool: ...

    def transaction_exists(self, transaction_id: str) -> bool: ...

    def read_plate(self, plate_id: str) -> tuple[AdapterPlateMeshState, ...]: ...

    def read_plate_design(self, plate_id: str) -> AdapterPlateDesign: ...

    def capture_update_checkpoint(self, plate_id: str, transaction_id: str) -> Any: ...

    def update_adapter_plate(
        self,
        plate_id: str,
        transaction_id: str,
        spec: AdapterPlateMeshSpec,
    ) -> None: ...

    def existing_state_matches_update(
        self,
        checkpoint: Any,
        plate_id: str,
        transaction_id: str,
    ) -> bool: ...

    def commit_update_checkpoint(self, checkpoint: Any, transaction_id: str) -> None: ...

    def restore_update_checkpoint(
        self,
        checkpoint: Any,
        transaction_id: str,
    ) -> bool: ...
