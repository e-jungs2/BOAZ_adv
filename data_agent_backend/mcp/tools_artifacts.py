from __future__ import annotations

from typing import Any

from data_agent_backend.mcp.deps import context_from, get_services, result_wrap
from data_agent_backend.models.artifacts import ArtifactRegisterRequest
from data_agent_backend.models.tool_results import ToolResult
from data_agent_backend.services.factory import BackendServices


def artifact_register(payload: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
    return artifact_register_impl(payload=payload, context=context, services=get_services())


def artifact_register_impl(*, payload: dict[str, Any], context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.artifact_registry.register_artifact(ArtifactRegisterRequest(**payload), context_from(context, "artifact_register")))


def artifact_get(artifact_id: str) -> ToolResult:
    return artifact_get_impl(artifact_id=artifact_id, services=get_services())


def artifact_get_impl(*, artifact_id: str, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.artifact_registry.get_artifact(artifact_id))


def artifact_list(run_id: str | None = None, type: str | None = None) -> ToolResult:
    return artifact_list_impl(run_id=run_id, type=type, services=get_services())


def artifact_list_impl(*, run_id: str | None = None, type: str | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.artifact_registry.list_artifacts(run_id=run_id, type=type))


def artifact_preview(artifact_id: str) -> ToolResult:
    return artifact_preview_impl(artifact_id=artifact_id, services=get_services())


def artifact_preview_impl(*, artifact_id: str, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.artifact_registry.get_preview(artifact_id))


def artifact_lineage(artifact_id: str) -> ToolResult:
    return artifact_lineage_impl(artifact_id=artifact_id, services=get_services())


def artifact_lineage_impl(*, artifact_id: str, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.artifact_registry.get_lineage(artifact_id))
