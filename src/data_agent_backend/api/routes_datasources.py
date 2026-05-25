from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from data_agent_backend.api.common import ContextPayload, dump_result
from data_agent_backend.mcp.tools_datasources import (
    datasource_create_impl,
    datasource_get_catalog_impl,
    datasource_get_catalog_summary_impl,
    datasource_list_impl,
    datasource_query_impl,
    datasource_refresh_catalog_impl,
    datasource_test_impl,
)
from data_agent_backend.models.common import BackendModel, JsonDict
from data_agent_backend.services.factory import BackendServices

from .deps import get_backend_services


router = APIRouter(prefix="/datasources", tags=["datasources"])


class DatasourceCreatePayload(BackendModel):
    name: str
    host: str
    database: str
    username: str
    password: str
    kind: str = "mysql"
    port: int = 3306
    metadata: JsonDict = {}
    context: ContextPayload = None


class DatasourceContextPayload(BackendModel):
    context: ContextPayload = None


class DatasourceQueryPayload(BackendModel):
    query: str
    run_id: str
    row_limit: int = 1000
    context: ContextPayload = None


@router.post("")
def create_datasource(payload: DatasourceCreatePayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        datasource_create_impl(
            name=payload.name,
            host=payload.host,
            database=payload.database,
            username=payload.username,
            password=payload.password,
            kind=payload.kind,
            port=payload.port,
            metadata=payload.metadata,
            context=payload.context,
            services=services,
        )
    )


@router.get("")
def list_datasources(services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(datasource_list_impl(services=services))


@router.post("/{datasource_id}/test")
def test_datasource(datasource_id: str, payload: DatasourceContextPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(datasource_test_impl(datasource_id=datasource_id, context=payload.context, services=services))


@router.post("/{datasource_id}/refresh-catalog")
def refresh_catalog(datasource_id: str, payload: DatasourceContextPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(datasource_refresh_catalog_impl(datasource_id=datasource_id, context=payload.context, services=services))


@router.get("/{datasource_id}/catalog")
def get_catalog(datasource_id: str, table_name: str | None = None, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(datasource_get_catalog_impl(datasource_id=datasource_id, table_name=table_name, services=services))


@router.get("/{datasource_id}/catalog-summary")
def get_catalog_summary(datasource_id: str, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(datasource_get_catalog_summary_impl(datasource_id=datasource_id, services=services))


@router.post("/{datasource_id}/query")
def query_datasource(datasource_id: str, payload: DatasourceQueryPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        datasource_query_impl(
            datasource_id=datasource_id,
            query=payload.query,
            run_id=payload.run_id,
            row_limit=payload.row_limit,
            context=payload.context,
            services=services,
        )
    )
