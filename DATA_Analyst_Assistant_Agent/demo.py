from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

from data_agent_backend.config import BackendConfig
from data_agent_backend.models.approvals import ApprovalDecision

from DATA_Analyst_Assistant_Agent.backend_adapter import BackendAdapter
from DATA_Analyst_Assistant_Agent.models import OrchestrationState, SupervisorTerminalState
from DATA_Analyst_Assistant_Agent.supervisor import SQLAgentSupervisor


@dataclass(frozen=True)
class DemoScenario:
    name: str
    query: str
    auto_approve: bool = False


@dataclass(frozen=True)
class DemoRunResult:
    scenario: DemoScenario
    initial_state: OrchestrationState
    final_state: OrchestrationState
    auto_approved: bool = False
    artifact_paths: dict[str, list[str]] | None = None


DEFAULT_SCENARIOS: dict[str, tuple[DemoScenario, ...]] = {
    "simple": (DemoScenario("simple", "Show a simple revenue summary."),),
    "eda": (DemoScenario("eda", "Profile data quality and missing values, then make a report."),),
    "trend": (DemoScenario("trend", "Analyze monthly revenue trend with a chart."),),
    "mart": (DemoScenario("mart", "반복 조회용 데이터마트 저장 후보를 만들어줘.", auto_approve=True),),
    "full": (
        DemoScenario(
            "comprehensive",
            "배송 지연이 리뷰 점수에 미치는 영향을 분석하고, 지연율이 높은 셀러 상위 10개를 뽑아서 시각화해줘",
        ),
    ),
    "all": (
        DemoScenario("simple", "Show a simple revenue summary."),
        DemoScenario("eda", "Profile data quality and missing values, then make a report."),
        DemoScenario("trend", "Analyze monthly revenue trend with a chart."),
        DemoScenario(
            "comprehensive",
            "프로파일과 분석 인사이트를 만들고 월별 매출 추이 차트까지 포함한 종합 분석 보고서를 만들어줘.",
        ),
        DemoScenario("mart", "반복 조회용 데이터마트 저장 후보를 만들어줘.", auto_approve=True),
    ),
}


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a demo of the SQL agent orchestration pipeline.")
    parser.add_argument(
        "--scenario",
        choices=tuple(DEFAULT_SCENARIOS),
        help="Run a built-in demo flow instead of asking for a user query.",
    )
    parser.add_argument(
        "--query",
        help="Run a single custom query instead of a built-in scenario.",
    )
    parser.add_argument(
        "--base-data-dir",
        default=".demo_data",
        help="Base directory for backend state and generated demo artifacts.",
    )
    parser.add_argument("--thread-id", help="Optional thread id to attach to created runs.")
    parser.add_argument("--datasource-id", help="Optional datasource id to pass into the supervisor.")
    parser.add_argument(
        "--planner-mode",
        choices=("llm", "deterministic"),
        default="llm",
        help="Planner mode to use for demo runs. Defaults to llm.",
    )
    parser.add_argument(
        "--allow-planner-fallback",
        action="store_true",
        help="Allow llm planner mode to fall back to deterministic planning when llm planning is unavailable.",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable step-by-step progress output during demo execution.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed trace payloads during demo execution.",
    )
    parser.add_argument(
        "--show-llm-raw",
        action="store_true",
        help="Show raw LLM planner response.",
    )
    parser.add_argument("--hide-llm-raw", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--pause-on-approval",
        action="store_true",
        help="Leave approval-required runs in waiting state instead of auto-approving them.",
    )
    return parser


def resolve_scenarios(args: argparse.Namespace) -> tuple[DemoScenario, ...]:
    if args.query:
        return (DemoScenario("custom", args.query, auto_approve=not args.pause_on_approval),)
    if not args.scenario:
        query = input("질문을 입력하세요: ").strip()
        if not query:
            raise SystemExit("질문이 비어 있습니다.")
        return (DemoScenario("custom", query, auto_approve=not args.pause_on_approval),)
    scenarios = DEFAULT_SCENARIOS[args.scenario]
    if args.pause_on_approval:
        return tuple(DemoScenario(item.name, item.query, auto_approve=False) for item in scenarios)
    return scenarios


def run_demo_scenarios(
    scenarios: Iterable[DemoScenario],
    *,
    base_data_dir: str | Path = ".demo_data",
    thread_id: str | None = None,
    datasource_id: str | None = None,
    planner_mode: str = "llm",
    require_llm_planner: bool = True,
) -> list[DemoRunResult]:
    config = BackendConfig(base_data_dir=Path(base_data_dir))
    adapter = BackendAdapter(config=config)
    supervisor = SQLAgentSupervisor(adapter)
    results: list[DemoRunResult] = []

    for scenario in scenarios:
        initial_state = supervisor.run(
            scenario.query,
            thread_id=thread_id,
            datasource_id=datasource_id,
            planner_mode=planner_mode,
            require_llm_planner=require_llm_planner,
        )
        initial_snapshot = initial_state.model_copy(deep=True)
        final_state = initial_state
        auto_approved = False
        if (
            scenario.auto_approve
            and initial_state.terminal_state == SupervisorTerminalState.needs_user_approval
            and initial_state.approval_ids
        ):
            approval_id = initial_state.approval_ids[-1]
            adapter.services.approval_store.resolve_approval_request(approval_id, ApprovalDecision.approve)
            final_state = supervisor.resume_after_approval(initial_state, approval_id)
            auto_approved = True
        results.append(
            DemoRunResult(
                scenario=scenario,
                initial_state=initial_snapshot,
                final_state=final_state.model_copy(deep=True),
                auto_approved=auto_approved,
                artifact_paths=_artifact_paths(adapter, final_state),
            )
        )
    return results


def render_results(results: Iterable[DemoRunResult]) -> str:
    sections: list[str] = []
    for result in results:
        initial = result.initial_state
        final = result.final_state
        artifact_paths = result.artifact_paths or {}
        report_path = _first_path(artifact_paths, "report_agent")
        chart_path = _first_path(artifact_paths, "visualization_agent")
        analysis_path = _first_path(artifact_paths, "analysis_agent")
        eda_path = _first_path(artifact_paths, "eda_agent")
        lines = [
            "",
            "=== Demo Result ===",
            f"Query: {result.scenario.query}",
            f"Run: {final.run_id}",
            f"Route: {initial.route_kind}",
            f"Planner: {initial.planner_mode}",
            f"Status: {final.terminal_state.value if final.terminal_state else 'unknown'}",
        ]
        if final.generated_sql:
            lines.append(f"SQL: {final.generated_sql}")
        lines.append(f"Completed: {', '.join(final.completed_agents) if final.completed_agents else '-'}")
        if report_path:
            lines.append(f"Report: {report_path}")
        elif "report_agent" in final.artifact_ids:
            lines.append(f"Report artifact: {', '.join(final.artifact_ids['report_agent'])}")
        else:
            lines.append("Report: not generated")
        if eda_path:
            lines.append(f"EDA: {eda_path}")
        if analysis_path:
            lines.append(f"Analysis: {analysis_path}")
        if chart_path:
            lines.append(f"Chart spec: {chart_path}")
        if final.approval_ids:
            lines.append(f"Approval: {', '.join(final.approval_ids)}")
        if final.mart_id:
            lines.append(f"Mart: {final.mart_id}")
        if final.error_state:
            lines.append(f"Error: {final.error_state.get('code', 'unknown')}: {final.error_state.get('message', final.error_state)}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _artifact_paths(adapter: BackendAdapter, state: OrchestrationState) -> dict[str, list[str]]:
    paths: dict[str, list[str]] = {}
    for agent_name, artifact_ids in state.artifact_ids.items():
        for artifact_id in artifact_ids:
            try:
                artifact = adapter.get_artifact(artifact_id)
            except Exception:
                continue
            if artifact.local_path:
                paths.setdefault(agent_name, []).append(artifact.local_path)
    return paths


def _first_path(paths: dict[str, list[str]], agent_name: str) -> str | None:
    values = paths.get(agent_name) or []
    return values[0] if values else None


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    if args.no_stream:
        os.environ["SQL_AGENT_DEMO_TRACE_LEVEL"] = "quiet"
    elif args.verbose:
        os.environ["SQL_AGENT_DEMO_TRACE_LEVEL"] = "verbose"
    else:
        os.environ["SQL_AGENT_DEMO_TRACE_LEVEL"] = "concise"
    if args.show_llm_raw and not args.hide_llm_raw:
        os.environ["SQL_AGENT_SHOW_LLM_RAW"] = "1"
    else:
        os.environ.pop("SQL_AGENT_SHOW_LLM_RAW", None)
    results = run_demo_scenarios(
        resolve_scenarios(args),
        base_data_dir=args.base_data_dir,
        thread_id=args.thread_id,
        datasource_id=args.datasource_id,
        planner_mode=args.planner_mode,
        require_llm_planner=args.planner_mode == "llm" and not args.allow_planner_fallback,
    )
    print(render_results(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
