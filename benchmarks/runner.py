"""中文评测入口：默认只查看数据，联网必须显式选择 live。"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

from bsa.infra.credentials import resolve_api_key
from bsa.planner.llm.openai_chat import OpenAICompatiblePlannerClient
from bsa.planner.openai_compatible import ProviderConnectionConfig, ProviderError, _NoRedirectHandler

from .evaluation import SceneFactory, evaluate_case, load_suite, replay_suite, review_case, summarize
from .fixture import memory_fixture
from .live import RequestBudgetOpener


def main(
    argv: list[str] | None = None, *, scene_factory: SceneFactory = memory_fixture,
    engine: str = "memory", default_mode: str = "review",
) -> int:
    """只使用公开夹具；命令行不接受 API Key，结果不保存秘密。"""
    parser = argparse.ArgumentParser(description="场景领航员固定任务评测（默认不联网）")
    parser.add_argument("--mode", choices=("review", "replay", "live"), default=default_mode)
    parser.add_argument("--case", action="append", dest="case_ids", help="只运行指定任务，可重复传入")
    parser.add_argument("--api-base", default=os.environ.get("BSA_API_BASE", ""))
    parser.add_argument("--model", default=os.environ.get("BSA_MODEL", ""))
    parser.add_argument("--max-requests", type=int, default=2, help="真实 HTTP 总上限，包含修复请求")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--output-format", choices=("json_object", "json_schema"), default="json_object")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    suite = load_suite()
    if args.case_ids:
        known = {case["case_id"] for case in suite["cases"]}
        if set(args.case_ids) - known:
            parser.error("指定的任务 ID 不存在")
        suite["cases"] = [case for case in suite["cases"] if case["case_id"] in args.case_ids]

    if args.mode == "review":
        report = {
            "mode": "review", "engine": engine, "suite_id": suite["suite_id"],
            "suite_sha256": suite["sha256"], "network_request_count": 0,
            "cases": [review_case(case) for case in suite["cases"]],
        }
    elif args.mode == "replay":
        report = replay_suite(suite, scene_factory=scene_factory)
        report["engine"] = engine
    else:
        if not args.api_base or not args.model:
            parser.error("真实模型模式需要 API 地址和模型名；未发出网络请求")
        if not 1 <= args.max_requests <= 100:
            parser.error("请求上限必须在 1 到 100 之间")
        try:
            config = ProviderConnectionConfig(args.api_base, args.model, args.timeout, args.output_format).validated_for_planning()
        except ProviderError as error:
            parser.error(str(error))
        credential = resolve_api_key("")
        bounded = RequestBudgetOpener(urllib.request.build_opener(_NoRedirectHandler()), args.max_requests)
        client = OpenAICompatiblePlannerClient(opener=bounded)
        print("真实模型模式：只发送公开合成任务；自动执行仅作用于一次性测试夹具。")
        print(f"HTTP 总请求上限：{args.max_requests}（修复请求也占额度）")
        results = []
        for case in suite["cases"]:
            before_count = bounded.request_count
            result = evaluate_case(
                case, planner=lambda request: client.plan(config, credential.value, request),
                mode="live", scene_factory=scene_factory,
            )
            # 失败没有 PlannerResponse 时，仍保留实际已尝试的 HTTP 次数。
            result["network_requests"] = bounded.request_count - before_count
            result["repair_count"] = max(0, result["network_requests"] - 1)
            results.append(result)
            print(f"{case['case_id']}：{result['execution_status']}，任务通过={result['passed']}")
        report = summarize(suite, results, mode="live")
        report.update(engine=engine, model=config.model, max_requests=args.max_requests,
                      output_format=config.output_format)

    output = args.output or Path(__file__).parent / "results" / f"planning_{engine}_{args.mode}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"模式：{args.mode}；网络请求：{report['network_request_count']}；报告：{output.resolve()}")
    if args.mode == "review":
        print("仅审查数据，未调用模型，也未执行场景动作。")
    else:
        print(f"通过：{report['passed_count']}/{report['case_count']}；跳过：{report['skipped_count']}")
        if args.mode == "replay":
            print("这是人工固定候选的离线回放，不代表真实模型成功率。")
    return 0 if args.mode == "review" or all(
        item["passed"] or item["execution_status"] == "SKIPPED" for item in report["results"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
