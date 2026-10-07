"""Ports that isolate the deterministic application layer from Blender."""

from __future__ import annotations

from typing import Any, Protocol

from ..domain.scene import SceneSnapshot, Vector3


class ScenePort(Protocol):
    """Minimum state-changing surface required by M1 execution."""

    def read_snapshot(self) -> SceneSnapshot: ...

    def capture_checkpoint(self, object_ids: tuple[str, ...]) -> Any: ...

    def restore_checkpoint(self, checkpoint: Any) -> bool: ...

    def apply_location(self, object_id: str, location_world: Vector3) -> None: ...

    def set_locked(self, object_id: str, locked: bool) -> None: ...
