"""与界面和模型服务解耦的固定任务评测与独立状态判定。"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from bsa import __version__
from bsa.application.ports import ScenePort
from bsa.application.service import SceneEditingService
from bsa.core.diff import max_matrix_delta
from bsa.domain.errors import DomainError, ErrorCode
from bsa.domain.scene import SceneSnapshot
from bsa.infra.config import POSITION_EPS
from bsa.planner.context_builder import ContextBuilder
from bsa.planner.local_parser import LocalIntentParser
from bsa.planner.openai_compatible import ProviderError
from bsa.planner.plan_candidate import PlanCandidate, build_action_plan, candidate_action_schema
from bsa.planner.provider import PlannerRequest, PlannerResponse, PlannerUsage

from .fixture import memory_fixture
from .live import RequestBudgetExceeded


DEFAULT_SUITE = Path(__file__).parent / "cases" / "planning_v1.json"
Planner = Callable[[PlannerRequest], PlannerResponse]
SceneFactory = Callable[[dict[str, Any]], ScenePort]


def load_suite(path: Path = DEFAULT_SUITE) -> dict[str, Any]:
    """读取公开评测数据，固定哈希用于关联结果与任务版本。"""
    raw = path.read_bytes()
    suite = json.loads(raw.decode("utf-8"))
    if suite.get("schema_version") != "0.1" or not isinstance(suite.get("cases"), list):
        raise ValueError("评测任务集结构无效")
    ids = [case["case_id"] for case in suite["cases"]]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("任务 ID 不能为空或重复")
    suite["sha256"] = hashlib.sha256(raw).hexdigest()
    return suite


def planning_request(instruction: str, snapshot: SceneSnapshot) -> PlannerRequest:
    """与插件使用同一数据最小化规则；不包含任务预期答案。"""
    return PlannerRequest(instruction, ContextBuilder().build(instruction, snapshot).payload, candidate_action_schema())


def review_case(case: dict[str, Any]) -> dict[str, Any]:
    """只读查看公开夹具的发送数据；不访问 Provider。"""
    snapshot = memory_fixture(case).read_snapshot()
    try:
        LocalIntentParser().parse(case["instruction"], snapshot)
        return {"case_id": case["case_id"], "route": "local", "request": None}
    except DomainError as error:
        if error.code != ErrorCode.ACTION_NOT_SUPPORTED:
            return {"case_id": case["case_id"], "route": "local", "request": None, "error_code": error.code.value}
    return {"case_id": case["case_id"], "route": "ai", "request": asdict(planning_request(case["instruction"], snapshot))}


def _goal_checks(case: dict[str, Any], before: SceneSnapshot, after: SceneSnapshot) -> tuple[list[dict], list[str]]:
    before_map, after_map = before.object_map(), after.object_map()
    changed = [object_id for object_id in before_map if object_id not in after_map or (
        max_matrix_delta(before_map[object_id], after_map[object_id]) > POSITION_EPS
        or before_map[object_id].locked != after_map[object_id].locked
    )]
    changed.extend(object_id for object_id in after_map if object_id not in before_map)
    unauthorized = sorted(set(changed) - set(case["allowed_changes"]))
    checks = []
    for goal in case["goals"]:
        obj = after_map.get(goal["object_id"])
        passed = obj is not None
        if obj is not None and "location" in goal:
            passed &= max(abs(left - right) for left, right in zip(obj.location_world, goal["location"], strict=True)) <= POSITION_EPS
        if obj is not None and "locked" in goal:
            passed &= obj.locked is goal["locked"]
        checks.append({"object_id": goal["object_id"], "passed": bool(passed)})
    return checks, unauthorized


def evaluate_case(
    case: dict[str, Any], *, planner: Planner | None, mode: str,
    scene_factory: SceneFactory = memory_fixture,
) -> dict[str, Any]:
    """执行一个隔离夹具任务，再独立检查用户目标及允许变化集合。"""
    scene = scene_factory(case)
    before = scene.read_snapshot()
    started = time.perf_counter()
    route, status, error_code = "local", "NOT_EXECUTED", None
    usage, request_count, repair_count = None, 0, 0
    planner_invocations = 0
    try:
        try:
            plan = LocalIntentParser().parse(case["instruction"], before)
        except DomainError as error:
            if error.code != ErrorCode.ACTION_NOT_SUPPORTED:
                raise
            route = "ai"
            if planner is None:
                raise ValueError("AI 任务缺少规划器")
            request = planning_request(case["instruction"], before)
            planner_invocations = 1
            response = planner(request)
            usage = asdict(response.usage)
            request_count, repair_count = response.request_count, response.repair_count
            allowed_ids = [obj["object_id"] for obj in request.scene_context["objects"]]
            candidate = PlanCandidate.from_dict(response.plan_payload, allowed_object_ids=allowed_ids)
            plan = build_action_plan(candidate, before)
        result = SceneEditingService(scene).execute_plan(plan, confirmed=True)
        status = result.status
        if result.errors:
            error_code = result.errors[0].code.value
    except (DomainError, ProviderError) as error:
        status, error_code = "REJECTED", error.code.value
    except RequestBudgetExceeded:
        status, error_code = "SKIPPED", "REQUEST_BUDGET_EXCEEDED"

    after = scene.read_snapshot()
    checks, unauthorized = _goal_checks(case, before, after)
    unchanged = (
        set(before.object_map()) == set(after.object_map())
        and all(max_matrix_delta(before.object_map()[oid], after.object_map()[oid]) <= POSITION_EPS
                and before.object_map()[oid].locked is after.object_map()[oid].locked
                for oid in before.object_map())
    )
    expects_rejection = bool(case.get("expect_rejection"))
    task_success = not expects_rejection and status == "COMMITTED" and all(item["passed"] for item in checks) and not unauthorized
    rejection_passed = expects_rejection and status == "REJECTED" and error_code in case["expect_rejection"] and unchanged
    passed = (task_success or rejection_passed) and route == case["route"]
    return {
        "case_id": case["case_id"], "mode": mode, "route": route,
        "passed": passed, "task_success": task_success,
        "expected_rejection": expects_rejection, "rejection_passed": rejection_passed,
        "execution_status": status, "error_code": error_code,
        "goal_checks": checks, "task_unauthorized_changes": unauthorized,
        "scene_unchanged": unchanged, "planner_invocations": planner_invocations,
        "network_requests": request_count, "repair_count": repair_count, "usage": usage,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def summarize(suite: dict[str, Any], results: list[dict], *, mode: str) -> dict[str, Any]:
    """将任务成功和正确拒绝分开统计，回放不产生真实模型成功率。"""
    positive = [result for result in results if not result["expected_rejection"]]
    ai_positive = [result for result in positive if result["route"] == "ai"
                   and result["execution_status"] != "SKIPPED"
                   and result["network_requests"] > 0]
    successes = sum(result["task_success"] for result in positive)
    return {
        "schema_version": "0.1", "extension_version": __version__,
        "suite_id": suite["suite_id"], "suite_sha256": suite["sha256"], "mode": mode,
        "case_count": len(results), "passed_count": sum(item["passed"] for item in results),
        "positive_task_count": len(positive), "task_success_count": successes,
        "expected_rejection_count": sum(item["expected_rejection"] for item in results),
        "correct_rejection_count": sum(item["rejection_passed"] for item in results),
        "network_request_count": sum(item["network_requests"] for item in results),
        "local_task_count": sum(item["route"] == "local" for item in results),
        "skipped_count": sum(item["execution_status"] == "SKIPPED" for item in results),
        "measured_ai_task_count": len(ai_positive) if mode == "live" else 0,
        "real_model_success_rate": (
            sum(item["task_success"] for item in ai_positive) / len(ai_positive)
            if mode == "live" and ai_positive else None
        ),
        "task_unauthorized_change_count": sum(bool(item["task_unauthorized_changes"]) for item in results),
        "results": results,
    }


def replay_suite(suite: dict[str, Any], *, scene_factory: SceneFactory = memory_fixture) -> dict[str, Any]:
    """离线回放固定候选 JSON，覆盖规划校验和事务执行链。"""
    results = []
    for case in suite["cases"]:
        def replay(request: PlannerRequest, current=case) -> PlannerResponse:
            return PlannerResponse(
                suite["replay_plans"][current["replay_key"]],
                PlannerUsage("recorded_fixture", "replay", None, None, None, 0),
                None, 0, 0,
            )
        results.append(evaluate_case(case, planner=replay, mode="replay", scene_factory=scene_factory))
    return summarize(suite, results, mode="replay")
