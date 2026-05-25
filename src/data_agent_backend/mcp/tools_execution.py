from __future__ import annotations

from typing import Any

from data_agent_backend.mcp.deps import context_from, get_services, result_wrap
from data_agent_backend.models.artifacts import ArtifactRef, ArtifactType
from data_agent_backend.models.execution import ExecutionLimits
from data_agent_backend.models.tool_results import ToolResult
from data_agent_backend.services.factory import BackendServices


def sql_run_query(
    query: str,
    run_id: str,
    connection_id: str | None = None,
    row_limit: int = 1000,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    return sql_run_query_impl(
        query=query,
        run_id=run_id,
        connection_id=connection_id,
        row_limit=row_limit,
        context=context,
        services=get_services(),
    )


def sql_run_query_impl(
    *,
    query: str,
    run_id: str,
    connection_id: str | None = None,
    row_limit: int = 1000,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.sql_executor.run_sql_query(query, run_id, connection_id, context_from(context, "sql_run_query"), row_limit))


def sandbox_run_python(
    code: str,
    run_id: str,
    input_artifact_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
    *,
    timeout_ms: int | None = None,
) -> ToolResult:
    return sandbox_run_python_impl(
        code=code,
        run_id=run_id,
        input_artifact_ids=input_artifact_ids,
        context=context,
        timeout_ms=timeout_ms,
        services=get_services(),
    )


def sandbox_run_python_impl(
    *,
    code: str,
    run_id: str,
    input_artifact_ids: list[str] | None = None,
    timeout_ms: int | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    if timeout_ms is not None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
            return ToolResult.failure(
                "VALIDATION_ERROR",
                "timeout_ms must be an integer.",
                {"field": "timeout_ms"},
            )
        if timeout_ms <= 0 or timeout_ms > services.config.max_execution_timeout_ms:
            return ToolResult.failure(
                "VALIDATION_ERROR",
                f"timeout_ms must be between 1 and {services.config.max_execution_timeout_ms}.",
                {"field": "timeout_ms", "max_timeout_ms": services.config.max_execution_timeout_ms},
            )
    ctx = context_from(context, "sandbox_run_python")
    ctx = ctx.model_copy(update={"run_id": ctx.run_id or run_id})
    inputs = [ArtifactRef(artifact_id=item, type=ArtifactType.dataset) for item in (input_artifact_ids or [])]
    return result_wrap(lambda: services.sandbox_executor.run_python(code, inputs, ExecutionLimits(timeout_ms=timeout_ms), ctx))
