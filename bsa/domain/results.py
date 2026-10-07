"""Execution and verification result types."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .errors import DomainError


@dataclass(frozen=True)
class CheckResult:
    check_type: str
    object_ids: tuple[str, ...]
    expected: Any
    actual: Any
    tolerance: float | None
    passed: bool


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    checks: tuple[CheckResult, ...]
    unauthorized_changes: tuple[str, ...]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible verification payload."""
        return {
            "passed": self.passed,
            "checks": [asdict(check) for check in self.checks],
            "unauthorized_changes": list(self.unauthorized_changes),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    plan_id: str
    verification: VerificationResult | None
    errors: tuple[DomainError, ...] = ()
    rollback_verified: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the UI and benchmark result contract."""
        return {
            "status": self.status,
            "plan_id": self.plan_id,
            "verification": self.verification.to_dict() if self.verification else None,
            "errors": [error.to_dict() for error in self.errors],
            "rollback_verified": self.rollback_verified,
        }
