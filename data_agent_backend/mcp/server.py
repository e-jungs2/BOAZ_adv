from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from data_agent_backend.mcp.tools_approvals import approval_get, approval_list_pending, approval_resolve
from data_agent_backend.mcp.tools_artifacts import artifact_get, artifact_lineage, artifact_list, artifact_preview, artifact_register
from data_agent_backend.mcp.tools_catalog import catalog_get, catalog_list
from data_agent_backend.mcp.tools_db import (
    db_describe_table,
    db_get_schema,
    db_list_datasources,
    db_run_analysis_query,
    db_sample_rows,
)
from data_agent_backend.mcp.tools_execution import sandbox_run_python, sql_run_query
from data_agent_backend.mcp.tools_exports import export_create
from data_agent_backend.mcp.tools_memory import memory_get, memory_list, memory_propose, memory_search
from data_agent_backend.mcp.tools_policy import policy_evaluate
from data_agent_backend.mcp.tools_runs import run_append_event, run_create, run_get, run_list, run_list_events, run_summary, run_update_status
from data_agent_backend.mcp.tools_workspace import workspace_list, workspace_preview, workspace_read_text, workspace_write_text


DB_ANALYSIS_TOOLS: list[Callable[..., Any]] = [
    db_list_datasources,
    db_get_schema,
    db_describe_table,
    db_sample_rows,
    db_run_analysis_query,
]

LEGACY_TOOLS: list[Callable[..., Any]] = [
    workspace_list,
    workspace_read_text,
    workspace_write_text,
    workspace_preview,
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
    export_create,
]

FULL_TOOLS: list[Callable[..., Any]] = [*LEGACY_TOOLS, *DB_ANALYSIS_TOOLS]


def get_mcp_tools_for_profile(profile: str) -> list[Callable[..., Any]]:
    if profile == "db_analysis":
        return DB_ANALYSIS_TOOLS
    if profile == "full":
        return FULL_TOOLS
    raise ValueError(f"Unsupported MCP profile: {profile}")


def create_mcp_server(profile: str | None = None) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - mcp package is only needed at runtime
        raise RuntimeError("The mcp package is required to run the MCP server.") from exc

    server = FastMCP("data-agent-backend")
    selected_profile = profile or os.environ.get("DATA_AGENT_MCP_PROFILE", "db_analysis")
    for fn in get_mcp_tools_for_profile(selected_profile):
        server.tool()(fn)
    return server


def main() -> None:
    create_mcp_server().run()


if __name__ == "__main__":
    main()
