from __future__ import annotations

from typing import Any

from data_agent_backend.mcp.deps import context_from, get_services, result_wrap
from data_agent_backend.models.tool_results import ToolResult
from data_agent_backend.services.factory import BackendServices


def memory_propose(
    namespace: list[str],
    type: str,
    content: Any,
    source: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    return memory_propose_impl(
        namespace=namespace,
        type=type,
        content=content,
        source=source,
        metadata=metadata,
        context=context,
        services=get_services(),
    )


def memory_propose_impl(
    *,
    namespace: list[str],
    type: str,
    content: Any,
    source: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.memory_store.propose_memory(namespace, type, content, source, metadata, context_from(context, "memory_propose")))


def memory_list(namespace: list[str], type: str | None = None, context: dict[str, Any] | None = None) -> ToolResult:
    return memory_list_impl(namespace=namespace, type=type, context=context, services=get_services())


def memory_list_impl(
    *,
    namespace: list[str],
    type: str | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.memory_store.list_memory(namespace, type))


def memory_get(memory_id: str, context: dict[str, Any] | None = None) -> ToolResult:
    return memory_get_impl(memory_id=memory_id, context=context, services=get_services())


def memory_get_impl(*, memory_id: str, context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.memory_store.get_memory(memory_id))


def memory_search(namespace: list[str], query: str, type: str | None = None, context: dict[str, Any] | None = None) -> ToolResult:
    return memory_search_impl(namespace=namespace, query=query, type=type, context=context, services=get_services())


def memory_search_impl(
    *,
    namespace: list[str],
    query: str,
    type: str | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.memory_store.search_memory(query, namespace, type))
