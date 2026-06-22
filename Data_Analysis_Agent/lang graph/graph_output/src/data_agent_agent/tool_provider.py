from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from data_agent_agent.config import AgentConfig
from data_agent_agent.mcp_client import load_backend_tools
from data_agent_backend.mcp.tools_analysis_context import analysis_build_context_impl
from data_agent_backend.mcp.tools_datasources import (
    datasource_create_impl,
    datasource_get_catalog_summary_impl,
    datasource_list_impl,
    datasource_query_impl,
    datasource_refresh_catalog_impl,
    datasource_test_impl,
)
from data_agent_backend.mcp.tools_execution import sandbox_run_python_impl
from data_agent_backend.mcp.tools_runs import run_create_impl
from data_agent_backend.services.factory import BackendServices


RawToolLoader = Callable[[AgentConfig], Awaitable[dict[str, Any]] | dict[str, Any]]


class BackendToolProvider(Protocol):
    async def load_tools(self, config: AgentConfig) -> dict[str, Any]:
        ...


class FunctionBackendToolProvider:
    def __init__(self, loader: RawToolLoader) -> None:
        self.loader = loader

    async def load_tools(self, config: AgentConfig) -> dict[str, Any]:
        result = self.loader(config)
        if inspect.isawaitable(result):
            result = await result
        return result


class MCPBackendToolProvider:
    async def load_tools(self, config: AgentConfig) -> dict[str, Any]:
        return await load_backend_tools(config)


class InProcessRawTool:
    def __init__(self, name: str, fn: Callable[..., Any], services: BackendServices) -> None:
        self.name = name
        self.fn = fn
        self.services = services

    async def ainvoke(self, payload: dict[str, Any]) -> Any:
        tool_payload = payload.copy()
        tool_payload.pop("services", None)
        result = self.fn(**tool_payload, services=self.services)
        if inspect.isawaitable(result):
            result = await result
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return result


class InProcessBackendToolProvider:
    def __init__(self, services: BackendServices) -> None:
        self.services = services

    async def load_tools(self, _config: AgentConfig) -> dict[str, Any]:
        tools = {
            "run_create": run_create_impl,
            "datasource_list": datasource_list_impl,
            "datasource_create": datasource_create_impl,
            "datasource_test": datasource_test_impl,
            "datasource_refresh_catalog": datasource_refresh_catalog_impl,
            "datasource_get_catalog_summary": datasource_get_catalog_summary_impl,
            "analysis_build_context": analysis_build_context_impl,
            "datasource_query": datasource_query_impl,
            "sandbox_run_python": sandbox_run_python_impl,
        }
        return {name: InProcessRawTool(name, fn, self.services) for name, fn in tools.items()}
