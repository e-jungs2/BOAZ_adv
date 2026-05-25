from __future__ import annotations

from typing import Any

from data_agent_backend.mcp.deps import context_from, get_services, result_wrap
from data_agent_backend.models.datasources import DatasourceCreateRequest, DatasourceKind
from data_agent_backend.models.tool_results import ToolResult
from data_agent_backend.services.factory import BackendServices


def datasource_create(
    name: str,
    host: str,
    database: str,
    username: str,
    password: str,
    kind: str = "mysql",
    port: int = 3306,
    metadata: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    return datasource_create_impl(
        name=name,
        host=host,
        database=database,
        username=username,
        password=password,
        kind=kind,
        port=port,
        metadata=metadata,
        context=context,
        services=get_services(),
    )


def datasource_create_impl(
    *,
    name: str,
    host: str,
    database: str,
    username: str,
    password: str,
    kind: str = "mysql",
    port: int = 3306,
    metadata: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(
        lambda: services.datasource_service.create_datasource(
            DatasourceCreateRequest(
                name=name,
                kind=DatasourceKind(kind),
                host=host,
                port=port,
                database=database,
                username=username,
                password=password,
                metadata=metadata or {},
            ),
            context_from(context, "datasource_create"),
        )
    )


def datasource_test(
    datasource_id: str,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    return datasource_test_impl(datasource_id=datasource_id, context=context, services=get_services())


def datasource_test_impl(*, datasource_id: str, context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.datasource_service.test_datasource(datasource_id, context_from(context, "datasource_test")))


def datasource_list(context: dict[str, Any] | None = None) -> ToolResult:
    return datasource_list_impl(context=context, services=get_services())


def datasource_list_impl(*, context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.datasource_service.list_datasources(context_from(context, "datasource_list")))


def datasource_refresh_catalog(
    datasource_id: str,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    return datasource_refresh_catalog_impl(datasource_id=datasource_id, context=context, services=get_services())


def datasource_refresh_catalog_impl(*, datasource_id: str, context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.datasource_service.refresh_catalog(datasource_id, context_from(context, "datasource_refresh_catalog")))


def datasource_get_catalog(
    datasource_id: str,
    table_name: str | None = None,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    return datasource_get_catalog_impl(
        datasource_id=datasource_id,
        table_name=table_name,
        context=context,
        services=get_services(),
    )


def datasource_get_catalog_impl(
    *,
    datasource_id: str,
    table_name: str | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.datasource_service.get_catalog(datasource_id, table_name, context_from(context, "datasource_get_catalog")))


def datasource_get_catalog_summary(
    datasource_id: str,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    return datasource_get_catalog_summary_impl(datasource_id=datasource_id, context=context, services=get_services())


def datasource_get_catalog_summary_impl(
    *,
    datasource_id: str,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.datasource_service.get_catalog_summary(datasource_id, context_from(context, "datasource_get_catalog_summary")))


def datasource_query(
    datasource_id: str,
    query: str,
    run_id: str,
    row_limit: int = 1000,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    return datasource_query_impl(
        datasource_id=datasource_id,
        query=query,
        run_id=run_id,
        row_limit=row_limit,
        context=context,
        services=get_services(),
    )


def datasource_query_impl(
    *,
    datasource_id: str,
    query: str,
    run_id: str,
    row_limit: int = 1000,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.datasource_service.query_datasource(datasource_id, query, run_id, row_limit, context_from(context, "datasource_query")))
