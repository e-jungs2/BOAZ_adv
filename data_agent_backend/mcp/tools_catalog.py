from __future__ import annotations

from typing import Any

from data_agent_backend.mcp.deps import context_from, get_services, result_wrap
from data_agent_backend.models.tool_results import ToolResult
from data_agent_backend.services.factory import BackendServices


def catalog_list(context: dict[str, Any] | None = None) -> ToolResult:
    return catalog_list_impl(context=context, services=get_services())


def catalog_list_impl(*, context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.catalog_store.list(context_from(context, "catalog_list")))


def catalog_get(path_or_name: str, context: dict[str, Any] | None = None) -> ToolResult:
    return catalog_get_impl(path_or_name=path_or_name, context=context, services=get_services())


def catalog_get_impl(*, path_or_name: str, context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.catalog_store.read_text(path_or_name, context_from(context, "catalog_get")))
