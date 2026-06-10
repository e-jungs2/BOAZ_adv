from __future__ import annotations

from typing import Any

from data_agent_backend.mcp.deps import context_from, get_services, result_wrap
from data_agent_backend.models.contexts import PolicyContext
from data_agent_backend.models.tool_results import ToolResult
from data_agent_backend.services.factory import BackendServices


def db_list_datasources(
    context: dict[str, Any] | None = None,
    services: BackendServices | None = None,
) -> ToolResult:
    services = services or get_services()
    return result_wrap(lambda: services.datasource_service.list_agent_datasources())


def db_get_schema(
    datasource_id: str | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices | None = None,
) -> ToolResult:
    services = services or get_services()
    return result_wrap(lambda: services.datasource_service.get_schema(datasource_id))


def db_describe_table(
    table_name: str,
    datasource_id: str | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices | None = None,
) -> ToolResult:
    services = services or get_services()
    return result_wrap(lambda: services.datasource_service.describe_table(datasource_id, table_name))


def db_sample_rows(
    table_name: str,
    datasource_id: str | None = None,
    limit: int | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices | None = None,
) -> ToolResult:
    services = services or get_services()
    return result_wrap(lambda: services.datasource_service.sample_rows(datasource_id, table_name, limit))


def _ensure_run(services: BackendServices, context: PolicyContext) -> str:
    if context.run_id:
        return context.run_id
    run = services.run_service.create_run(thread_id=context.thread_id, project_id=context.project_id, context=context)
    return run.run_id


def db_run_analysis_query(
    query: str,
    datasource_id: str | None = None,
    row_limit: int | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices | None = None,
) -> ToolResult:
    services = services or get_services()
    ctx = context_from(context, "db_run_analysis_query")

    def _run():
        run_id = _ensure_run(services, ctx)
        effective_context = ctx.model_copy(update={"run_id": run_id})
        return services.sql_executor.run_analysis_query(
            query=query,
            run_id=run_id,
            datasource_id=datasource_id,
            context=effective_context,
            row_limit=row_limit,
        )

    return result_wrap(_run)
