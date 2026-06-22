from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any, Awaitable, Callable, Sequence

from data_agent_agent.config import AgentConfig, AgentConfigError
from data_agent_agent.deep_agent import create_data_agent
from data_agent_agent.mcp_client import BackendMCPToolError, load_backend_tools
from data_agent_agent.runtime import (
    AgentRunRequest,
    AgentRunResult,
    AgentRuntime,
    AgentRuntimeError,
    extract_final_content,
    resolve_datasource_id,
)
from data_agent_agent.tool_provider import FunctionBackendToolProvider, MCPBackendToolProvider

LoadToolsFunc = Callable[[AgentConfig], Awaitable[dict[str, Any]]]
AgentFactory = Callable[..., Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data-agent-agent")
    parser.add_argument(
        "--datasource-id",
        help="사용할 datasource ID. 생략하면 .env의 DATA_AGENT_MYSQL_* 값으로 자동 준비합니다.",
    )
    parser.add_argument("--model", help="OPENAI_MODEL 대신 사용할 OpenAI 모델명")
    parser.add_argument("--row-limit", type=int, help="SQL 기본 row limit")
    parser.add_argument("--python-timeout-ms", type=int, help="Python sandbox 기본 timeout(ms)")
    parser.add_argument("question", help="분석 질문")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


async def run_cli(
    *,
    datasource_id: str | None = None,
    question: str,
    model: str | None = None,
    row_limit: int | None = None,
    python_timeout_ms: int | None = None,
    config: AgentConfig | None = None,
    load_tools_func: LoadToolsFunc = load_backend_tools,
    agent_factory: AgentFactory = create_data_agent,
) -> AgentRunResult:
    runtime = AgentRuntime(
        config=config,
        tool_provider=(
            FunctionBackendToolProvider(load_tools_func)
            if load_tools_func is not load_backend_tools
            else MCPBackendToolProvider()
        ),
        agent_factory=agent_factory,
    )
    return await runtime.run(
        AgentRunRequest(
            datasource_id=datasource_id,
            question=question,
            model=model,
            row_limit=row_limit,
            python_timeout_ms=python_timeout_ms,
        )
    )


def format_cli_error(exc: Exception) -> str:
    details = getattr(exc, "details", {}) or {}
    parts = [str(exc)]
    bootstrap_step = details.get("bootstrap_step")
    if bootstrap_step:
        parts.append(f"단계: {bootstrap_step}")
    suggestion = details.get("suggestion")
    if suggestion:
        parts.append(f"제안: {suggestion}")
    if details.get("retryable") is True:
        parts.append("재시도 가능: 예")
    elif details.get("retryable") is False:
        parts.append("재시도 가능: 아니오")
    return " | ".join(parts)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = asyncio.run(
            run_cli(
                datasource_id=args.datasource_id,
                question=args.question,
                model=args.model,
                row_limit=args.row_limit,
                python_timeout_ms=args.python_timeout_ms,
            )
        )
    except (AgentConfigError, BackendMCPToolError, AgentRuntimeError) as exc:
        print(f"오류: {format_cli_error(exc)}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.answer)
    print(f"\nrun_id: {result.run_id}")


if __name__ == "__main__":
    main()
