from __future__ import annotations

import inspect
from functools import wraps
from typing import Any, get_type_hints

from data_agent_backend.mcp.tools_approvals import approval_get, approval_list_pending, approval_resolve
from data_agent_backend.mcp.tools_analysis_context import (
    analysis_build_context,
    analysis_catalog_search,
    analysis_get_column_profile,
    analysis_get_join_paths,
    analysis_get_table_profile,
    analysis_load_semantic_seed,
    analysis_profile_datasource,
    analysis_semantic_search,
    analysis_upsert_business_term,
    analysis_upsert_column_profile,
    analysis_upsert_join_path,
    analysis_upsert_mart,
    analysis_upsert_metric,
    analysis_upsert_table_profile,
)
from data_agent_backend.mcp.tools_artifacts import artifact_get, artifact_lineage, artifact_list, artifact_preview, artifact_register
from data_agent_backend.mcp.tools_catalog import catalog_get, catalog_list
from data_agent_backend.mcp.tools_datasources import (
    datasource_create,
    datasource_get_catalog,
    datasource_get_catalog_summary,
    datasource_list,
    datasource_query,
    datasource_refresh_catalog,
    datasource_test,
)
from data_agent_backend.mcp.tools_execution import sandbox_run_python, sql_run_query
from data_agent_backend.mcp.tools_exports import export_create
from data_agent_backend.mcp.tools_memory import memory_get, memory_list, memory_propose, memory_search
from data_agent_backend.mcp.tools_policy import policy_evaluate
from data_agent_backend.mcp.tools_runs import run_append_event, run_create, run_get, run_list, run_list_events, run_summary, run_update_status
from data_agent_backend.mcp.tools_workspace import workspace_list, workspace_preview, workspace_read_text, workspace_write_text


def _mcp_public_tool(fn: Any) -> Any:
    signature = inspect.signature(fn)
    type_hints = get_type_hints(fn)
    public_parameters = [
        param.replace(annotation=type_hints.get(name, param.annotation))
        for name, param in signature.parameters.items()
        if name != "services"
    ]

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        kwargs.pop("services", None)
        return fn(*args, **kwargs)

    wrapper.__signature__ = signature.replace(parameters=public_parameters, return_annotation=inspect.Signature.empty)  # type: ignore[attr-defined]
    wrapper.__annotations__ = {name: value for name, value in type_hints.items() if name != "services" and name != "return"}
    wrapper.__annotations__["return"] = Any
    return wrapper


def create_mcp_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - mcp가 설치되지 않았을 때만 실행됨
        raise RuntimeError("The mcp package is required to run the MCP server.") from exc

    server = FastMCP("data-agent-backend")
    for fn in [
        workspace_list,
        workspace_read_text,
        workspace_write_text,
        workspace_preview,
        analysis_catalog_search,
        analysis_get_table_profile,
        analysis_get_column_profile,
        analysis_semantic_search,
        analysis_get_join_paths,
        analysis_build_context,
        analysis_profile_datasource,
        analysis_load_semantic_seed,
        analysis_upsert_table_profile,
        analysis_upsert_column_profile,
        analysis_upsert_metric,
        analysis_upsert_business_term,
        analysis_upsert_mart,
        analysis_upsert_join_path,
        run_create,
        run_get,
        run_list,
        run_update_status,
        run_append_event,
        run_list_events,
        run_summary,
        artifact_register,
        artifact_get,
        artifact_list,
        artifact_preview,
        artifact_lineage,
        memory_propose,
        memory_list,
        memory_get,
        memory_search,
        approval_list_pending,
        approval_get,
        approval_resolve,
        policy_evaluate,
        sql_run_query,
        sandbox_run_python,
        catalog_list,
        catalog_get,
        datasource_create,
        datasource_test,
        datasource_list,
        datasource_refresh_catalog,
        datasource_get_catalog,
        datasource_get_catalog_summary,
        datasource_query,
        export_create,
    ]:
        server.tool()(_mcp_public_tool(fn))
    return server


def main() -> None:
    create_mcp_server().run()


if __name__ == "__main__":
    main()
