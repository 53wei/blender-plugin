"""矩形转接板真实网格的全有或全无创建事务。"""

from __future__ import annotations

import re

from .adapter_plate_ports import AdapterPlateCreationPort, AdapterPlateUpdatePort
from ..core.adapter_plate_mesh import (
    build_adapter_plate_mesh_spec,
    verify_adapter_plate_mesh,
)
from ..domain.adapter_plate import AdapterPlateDesign
from ..domain.adapter_plate_mesh import AdapterPlateCreationPlan, AdapterPlateUpdatePlan
from ..domain.errors import DomainError, ErrorCode
from ..domain.results import ExecutionResult

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _validate_plan(plan: AdapterPlateCreationPlan) -> None:
    if plan.schema_version != "0.1":
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "不支持的转接板创建计划版本",
            {"schema_version": plan.schema_version},
        )
    for field, value in (("plan_id", plan.plan_id), ("plate_id", plan.plate_id)):
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise DomainError(
                ErrorCode.PLAN_SCHEMA_INVALID,
                f"{field} 格式无效",
                {"field": field},
            )
    if not isinstance(plan.source, str) or not plan.source.strip():
        raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "source 不能为空")
    if not isinstance(plan.user_summary, str):
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "user_summary 必须是字符串",
        )
    if not isinstance(plan.design, AdapterPlateDesign):
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "design 必须是已验证的转接板规格",
        )
    if plan.design.plate_id != plan.plate_id:
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "计划板 ID 与设计板 ID 不一致",
        )
    if plan.requires_confirmation is not True:
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "转接板创建计划必须要求用户确认",
        )


def _world_holes(
    design: AdapterPlateDesign,
) -> dict[str, tuple[str, float, float, float]]:
    return {
        hole.hole_id: (
            hole.pattern_id,
            hole.center_mm[0] + design.origin_offset_mm[0],
            hole.center_mm[1] + design.origin_offset_mm[1],
            hole.diameter_mm,
        )
        for hole in design.holes
    }


def validate_adapter_plate_update_plan(plan: AdapterPlateUpdatePlan) -> None:
    if plan.schema_version != "0.1":
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "不支持的转接板更新计划版本",
            {"schema_version": plan.schema_version},
        )
    for field, value in (("plan_id", plan.plan_id), ("plate_id", plan.plate_id)):
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
    if not isinstance(plan.before_design, AdapterPlateDesign) or not isinstance(
        plan.design, AdapterPlateDesign
    ):
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "更新前后设计必须是严格转接板规格",
        )
    if (
        plan.before_design.plate_id != plan.plate_id
        or plan.design.plate_id != plan.plate_id
    ):
        raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "更新计划板 ID 不一致")
    if plan.requires_confirmation is not True:
        raise DomainError(
            ErrorCode.PLAN_SCHEMA_INVALID,
            "转接板更新计划必须要求用户确认",
        )
    before = build_adapter_plate_mesh_spec(plan.before_design)
    after = build_adapter_plate_mesh_spec(plan.design)
    if before.size_mm[2] != after.size_mm[2]:
        raise DomainError(
            ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
            "P4 暂不支持修改板厚",
        )
    if before.corner_radius_mm != after.corner_radius_mm:
        raise DomainError(
            ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
            "P4 暂不支持修改圆角",
        )
    if before.size_mm[:2] == after.size_mm[:2]:
        raise DomainError(ErrorCode.PLAN_SCHEMA_INVALID, "板宽或板深必须发生变化")
    before_holes = _world_holes(plan.before_design)
    after_holes = _world_holes(plan.design)
    if set(before_holes) != set(after_holes) or any(
        before_holes[hole_id][0] != after_holes[hole_id][0]
        or any(
            abs(left - right) > 1e-6
            for left, right in zip(
                before_holes[hole_id][1:],
                after_holes[hole_id][1:],
                strict=True,
            )
        )
        for hole_id in before_holes
    ):
        raise DomainError(
            ErrorCode.SPATIAL_UNSUPPORTED_GEOMETRY,
            "P4 修改必须保持全部孔的孔组、世界位置和孔径",
        )


class AdapterPlateCreationService:
    """验证、创建、回读，并在任何失败点恢复创建前状态。"""

    def __init__(self, scene: AdapterPlateCreationPort) -> None:
        self._scene = scene

    def execute_plan(
        self,
        plan: AdapterPlateCreationPlan,
        *,
        confirmed: bool = False,
    ) -> ExecutionResult:
        if plan.requires_confirmation and not confirmed:
            error = DomainError(
                ErrorCode.PRECONDITION_FAILED,
                "创建转接板真实网格前需要用户明确确认",
            )
            return ExecutionResult(
                status="REJECTED",
                plan_id=plan.plan_id,
                verification=None,
                errors=(error,),
            )
        try:
            _validate_plan(plan)
            spec = build_adapter_plate_mesh_spec(plan.design)
            if self._scene.plate_exists(plan.plate_id):
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "同名转接板已经存在",
                    {"plate_id": plan.plate_id},
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
                "无法创建转接板检查点，场景未修改",
                {"exception_type": type(unexpected).__name__},
            )
            return ExecutionResult(
                status="REJECTED",
                plan_id=plan.plan_id,
                verification=None,
                errors=(error,),
            )

        try:
            self._scene.create_adapter_plate(plan.plate_id, plan.plan_id, spec)
            actual = self._scene.read_created_plates(plan.plan_id)
            existing_unchanged = self._scene.existing_state_matches(
                checkpoint,
                plan.plan_id,
            )
            verification = verify_adapter_plate_mesh(
                spec,
                actual,
                plate_id=plan.plate_id,
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
                "转接板网格执行器发生意外错误",
                {"exception_type": type(unexpected).__name__},
            )
            return self._rollback(plan.plan_id, checkpoint, error)

    def _rollback(
        self,
        plan_id: str,
        checkpoint: object,
        error: DomainError,
    ) -> ExecutionResult:
        try:
            rollback_verified = self._scene.restore_creation_checkpoint(
                checkpoint,
                plan_id,
            )
        except Exception:
            rollback_verified = False
        if not rollback_verified:
            rollback_error = DomainError(
                ErrorCode.ROLLBACK_FAILED,
                "转接板检查点恢复后无法验证",
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


class AdapterPlateUpdateService:
    """验证当前版本、替换网格、回读，并在失败时恢复旧版本。"""

    def __init__(self, scene: AdapterPlateUpdatePort) -> None:
        self._scene = scene

    def execute_plan(
        self,
        plan: AdapterPlateUpdatePlan,
        *,
        confirmed: bool = False,
    ) -> ExecutionResult:
        if plan.requires_confirmation and not confirmed:
            error = DomainError(
                ErrorCode.PRECONDITION_FAILED,
                "更新转接板真实网格前需要用户明确确认",
            )
            return ExecutionResult(
                status="REJECTED",
                plan_id=plan.plan_id,
                verification=None,
                errors=(error,),
            )
        try:
            validate_adapter_plate_update_plan(plan)
            before_spec = build_adapter_plate_mesh_spec(plan.before_design)
            after_spec = build_adapter_plate_mesh_spec(plan.design)
            if not self._scene.plate_exists(plan.plate_id):
                raise DomainError(
                    ErrorCode.OBJECT_NOT_FOUND,
                    "要修改的转接板不存在",
                    {"plate_id": plan.plate_id},
                )
            if self._scene.transaction_exists(plan.plan_id):
                raise DomainError(
                    ErrorCode.PRECONDITION_FAILED,
                    "计划 ID 已经执行过",
                    {"plan_id": plan.plan_id},
                )
            current_design = self._scene.read_plate_design(plan.plate_id)
            if current_design != plan.before_design:
                raise DomainError(
                    ErrorCode.PLAN_STALE,
                    "转接板设计已改变，请重新生成修改预览",
                )
            current = self._scene.read_plate(plan.plate_id)
            current_transaction = current[0].transaction_id if len(current) == 1 else ""
            current_verification = verify_adapter_plate_mesh(
                before_spec,
                current,
                plate_id=plan.plate_id,
                transaction_id=current_transaction,
                existing_scene_unchanged=True,
            )
            if not current_verification.passed:
                raise DomainError(
                    ErrorCode.PLAN_STALE,
                    "转接板实际网格与修改预览的起始版本不一致",
                )
        except DomainError as error:
            return ExecutionResult(
                status="REJECTED",
                plan_id=plan.plan_id,
                verification=None,
                errors=(error,),
            )

        try:
            checkpoint = self._scene.capture_update_checkpoint(
                plan.plate_id,
                plan.plan_id,
            )
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
                "无法创建转接板更新检查点，场景未修改",
                {"exception_type": type(unexpected).__name__},
            )
            return ExecutionResult(
                status="REJECTED",
                plan_id=plan.plan_id,
                verification=None,
                errors=(error,),
            )

        try:
            self._scene.update_adapter_plate(
                plan.plate_id,
                plan.plan_id,
                after_spec,
            )
            actual = self._scene.read_plate(plan.plate_id)
            existing_unchanged = self._scene.existing_state_matches_update(
                checkpoint,
                plan.plate_id,
                plan.plan_id,
            )
            verification = verify_adapter_plate_mesh(
                after_spec,
                actual,
                plate_id=plan.plate_id,
                transaction_id=plan.plan_id,
                existing_scene_unchanged=existing_unchanged,
            )
            if not verification.passed:
                error_code = (
                    ErrorCode.UNAUTHORIZED_CHANGE
                    if verification.unauthorized_changes
                    else ErrorCode.POSTCONDITION_FAILED
                )
                raise DomainError(error_code, verification.summary)
            self._scene.commit_update_checkpoint(checkpoint, plan.plan_id)
            return ExecutionResult(
                status="COMMITTED",
                plan_id=plan.plan_id,
                verification=verification,
            )
        except DomainError as error:
            return self._rollback(plan.plan_id, checkpoint, error)
        except Exception as unexpected:
            error = DomainError(
                ErrorCode.INTERNAL_ERROR,
                "转接板网格更新器发生意外错误",
                {"exception_type": type(unexpected).__name__},
            )
            return self._rollback(plan.plan_id, checkpoint, error)

    def _rollback(
        self,
        plan_id: str,
        checkpoint: object,
        error: DomainError,
    ) -> ExecutionResult:
        try:
            restored = self._scene.restore_update_checkpoint(checkpoint, plan_id)
        except Exception:
            restored = False
        if not restored:
            rollback_error = DomainError(
                ErrorCode.ROLLBACK_FAILED,
                "转接板更新检查点恢复后无法验证",
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
