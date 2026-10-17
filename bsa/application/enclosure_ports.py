"""隔离外壳装配预览应用层与 Blender 的端口。"""

from __future__ import annotations

from typing import Any, Protocol

from ..domain.enclosure_preview import EnclosurePartSpec, EnclosurePartState


class EnclosurePreviewPort(Protocol):
    """P1 创建事务允许调用的最小状态变更接口。"""

    def enclosure_exists(self, enclosure_id: str) -> bool: ...

    def transaction_exists(self, transaction_id: str) -> bool: ...

    def capture_creation_checkpoint(self, transaction_id: str) -> Any: ...

    def create_preview_parts(
        self,
        enclosure_id: str,
        transaction_id: str,
        parts: tuple[EnclosurePartSpec, ...],
    ) -> None: ...

    def read_created_parts(
        self, transaction_id: str
    ) -> tuple[EnclosurePartState, ...]: ...

    def existing_state_matches(self, checkpoint: Any, transaction_id: str) -> bool: ...

    def restore_creation_checkpoint(self, checkpoint: Any, transaction_id: str) -> bool: ...
