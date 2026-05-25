from __future__ import annotations

from typing import Any

from data_agent_backend.mcp.deps import context_from, get_services, result_wrap
from data_agent_backend.models.tool_results import ToolResult
from data_agent_backend.services.factory import BackendServices


def export_create(
    artifact_id: str,
    format: str,
    destination: str | None = None,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    return export_create_impl(
        artifact_id=artifact_id,
        format=format,
        destination=destination,
        context=context,
        services=get_services(),
    )


def export_create_impl(
    *,
    artifact_id: str,
    format: str,
    destination: str | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.export_service.create_export(artifact_id, format, destination, context_from(context, "export_create")))
