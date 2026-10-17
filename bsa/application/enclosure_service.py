"""参数化外壳装配预览的全有或全无创建事务。"""

from __future__ import annotations

import re

from .enclosure_ports import EnclosurePreviewPort
from ..core.enclosure_preview import (
    build_enclosure_preview_parts,
    verify_enclosure_preview,
)
from ..domain.enclosure import EnclosureDesign
from ..domain.enclosure_preview import EnclosurePreviewPlan
from ..domain.errors import DomainError, ErrorCode
from ..domain.results import ExecutionResult

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _validate_plan(plan: EnclosurePreviewPlan) -> None:
    if plan.schema_version != "0.1":
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "不支持的外壳预览计划版本",
            {"schema_version": plan.schema_version},
        )
    for field, value in (
        ("plan_id", plan.plan_id),
        ("enclosure_id", plan.enclosure_id),
    ):
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise DomainError(
                ErrorCode.PLAN_SCHEMA_INVALID,
                f"{field} 格式无效",
                {"field": field},
            )
    if not isinstance(plan.source, str) or not plan.source.strip():
        raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "source 不能为空")
    if not isinstance(plan.user_summary, str):
        raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "user_summary 必须是字符串")
    if not isinstance(plan.design, EnclosureDesign):
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "design 必须是已验证的外壳规格",
        )
    if plan.requires_confirmation is not True:
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "外壳创建计划必须要求用户确认",
        )


class EnclosurePreviewService:
    """验证、创建、后置检查，并在任一失败点回滚新物体。"""

    def __init__(self, scene: EnclosurePreviewPort) -> None:
        self._scene = scene

    def execute_plan(
        self, plan: EnclosurePreviewPlan, *, confirmed: bool = False
    ) -> ExecutionResult:
        if plan.requires_confirmation and not confirmed:
            error = DomainError(
                ErrorCode.PRECONDITION_FAILED,
                "创建外壳预览前需要用户明确确认",
            )
            return ExecutionResult(
                status="REJECTED",
                plan_id=plan.plan_id,
                verification=None,
                errors=(error,),
            )
        try:
            _validate_plan(plan)
            parts = build_enclosure_preview_parts(plan.design)
            if self._scene.enclosure_exists(plan.enclosure_id):
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "同名外壳预览已经存在",
                    {"enclosure_id": plan.enclosure_id},
                )
            if self._scene.transaction_exists(plan.plan_id):
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "计划 ID 已经执行过",
                    {"plan_id": plan.plan_id},
                )
        except DomainError as error:
            return ExecutionResult(
                status="REJECTED",
                plan_id=plan.plan_id,
                verification=None,
                errors=(error,),
            )

        try:
            checkpoint = self._scene.capture_creation_checkpoint(plan.plan_id)
        except DomainError as error:
            return ExecutionResult(
                status="REJECTED",
                plan_id=plan.plan_id,
                verification=None,
                errors=(error,),
            )
        except Exception as unexpected:
            error = DomainError(
                ErrorCode.INTERNAL_ERROR,
                "无法创建外壳预览检查点，场景未修改",
                {"exception_type": type(unexpected).__name__},
            )
            return ExecutionResult(
                status="REJECTED",
                plan_id=plan.plan_id,
                verification=None,
                errors=(error,),
            )
        try:
            self._scene.create_preview_parts(
                plan.enclosure_id, plan.plan_id, parts
            )
            actual = self._scene.read_created_parts(plan.plan_id)
            existing_unchanged = self._scene.existing_state_matches(
                checkpoint, plan.plan_id
            )
            verification = verify_enclosure_preview(
                parts,
                actual,
                enclosure_id=plan.enclosure_id,
                transaction_id=plan.plan_id,
                existing_scene_unchanged=existing_unchanged,
            )
            if verification.passed:
                return ExecutionResult(
                    status="COMMITTED",
                    plan_id=plan.plan_id,
                    verification=verification,
                )
            error_code = (
                ErrorCode.UNAUTHORIZED_CHANGE
                if verification.unauthorized_changes
                else ErrorCode.POSTCONDITION_FAILED
            )
            raise DomainError(error_code, verification.summary)
        except DomainError as error:
            return self._rollback(plan.plan_id, checkpoint, error)
        except Exception as unexpected:
            error = DomainError(
                ErrorCode.INTERNAL_ERROR,
                "外壳预览执行器发生意外错误",
                {"exception_type": type(unexpected).__name__},
            )
            return self._rollback(plan.plan_id, checkpoint, error)

    def _rollback(self, plan_id: str, checkpoint: object, error: DomainError) -> ExecutionResult:
        try:
            rollback_verified = self._scene.restore_creation_checkpoint(
                checkpoint, plan_id
            )
        except Exception:
            rollback_verified = False
        if not rollback_verified:
            rollback_error = DomainError(
                ErrorCode.ROLLBACK_FAILED,
                "外壳预览检查点恢复后无法验证",
            )
            return ExecutionResult(
                status="ROLLBACK_FAILED",
                plan_id=plan_id,
                verification=None,
                errors=(error, rollback_error),
                rollback_verified=False,
            )
        return ExecutionResult(
            status="ROLLED_BACK",
            plan_id=plan_id,
            verification=None,
            errors=(error,),
            rollback_verified=True,
        )
