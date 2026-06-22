from __future__ import annotations

from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from data_agent_agent.config import AgentConfig


REQUIRED_BACKEND_TOOLS = {
    "run_create",
    "datasource_list",
    "datasource_create",
    "datasource_test",
    "datasource_refresh_catalog",
    "datasource_get_catalog_summary",
    "analysis_build_context",
    "datasource_query",
    "sandbox_run_python",
}


class BackendMCPToolError(RuntimeError):
    pass


async def load_backend_tools(config: AgentConfig) -> dict[str, Any]:
    client = MultiServerMCPClient(
        {
            "backend": {
                "command": config.mcp_command,
                "args": config.mcp_args,
                "transport": "stdio",
            }
        }
    )
    tools = await client.get_tools(server_name="backend")
    return {tool.name: tool for tool in tools}


def require_backend_tools(raw_tools: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(REQUIRED_BACKEND_TOOLS - set(raw_tools))
    if missing:
        raise BackendMCPToolError(f"필수 Backend MCP tool이 없습니다: {', '.join(missing)}")
    return raw_tools
