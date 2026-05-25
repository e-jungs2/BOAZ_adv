from __future__ import annotations

from typing import Any

from data_agent_backend.mcp.deps import context_from, get_services, result_wrap
from data_agent_backend.models.tool_results import ToolResult
from data_agent_backend.services.factory import BackendServices


def workspace_list(path: str = "/", context: dict[str, Any] | None = None) -> ToolResult:
    return workspace_list_impl(path=path, context=context, services=get_services())


def workspace_list_impl(*, path: str = "/", context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.workspace_backend.list(path, context_from(context, "workspace_list")))


def workspace_read_text(path: str, context: dict[str, Any] | None = None) -> ToolResult:
    return workspace_read_text_impl(path=path, context=context, services=get_services())


def workspace_read_text_impl(*, path: str, context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.workspace_backend.read_text(path, context_from(context, "workspace_read_text")))


def workspace_write_text(path: str, content: str, context: dict[str, Any] | None = None) -> ToolResult:
    return workspace_write_text_impl(path=path, content=content, context=context, services=get_services())


def workspace_write_text_impl(*, path: str, content: str, context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.workspace_backend.write_text(path, content, context_from(context, "workspace_write_text")))


def workspace_preview(path_or_artifact_id: str, context: dict[str, Any] | None = None) -> ToolResult:
    return workspace_preview_impl(path_or_artifact_id=path_or_artifact_id, context=context, services=get_services())


def workspace_preview_impl(
    *,
    path_or_artifact_id: str,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.workspace_backend.preview(path_or_artifact_id, context_from(context, "workspace_preview")))
