"""Stable error codes used by the application and Blender UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Expected failures that callers can handle without parsing text."""

    PLAN_SCHEMA_INVALID = "PLAN_SCHEMA_INVALID"
    PLAN_STALE = "PLAN_STALE"
    OBJECT_NOT_FOUND = "OBJECT_NOT_FOUND"
    OBJECT_LOCKED = "OBJECT_LOCKED"
    ACTION_NOT_SUPPORTED = "ACTION_NOT_SUPPORTED"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    SPATIAL_UNSUPPORTED_GEOMETRY = "SPATIAL_UNSUPPORTED_GEOMETRY"
    POSTCONDITION_FAILED = "POSTCONDITION_FAILED"
    UNAUTHORIZED_CHANGE = "UNAUTHORIZED_CHANGE"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class DomainError(Exception):
    """A structured, user-safe domain failure."""

    code: ErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {"code": self.code.value, "message": self.message, "details": self.details}
