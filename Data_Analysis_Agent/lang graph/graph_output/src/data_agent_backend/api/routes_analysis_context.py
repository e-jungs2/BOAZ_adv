from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from data_agent_backend.api.common import dump_result
from data_agent_backend.mcp.tools_analysis_context import (
    analysis_build_context_impl,
    analysis_catalog_search_impl,
    analysis_get_column_profile_impl,
    analysis_get_join_paths_impl,
    analysis_get_table_profile_impl,
    analysis_load_semantic_seed_impl,
    analysis_profile_datasource_impl,
    analysis_semantic_search_impl,
    analysis_upsert_business_term_impl,
    analysis_upsert_column_profile_impl,
    analysis_upsert_join_path_impl,
    analysis_upsert_mart_impl,
    analysis_upsert_metric_impl,
    analysis_upsert_table_profile_impl,
)
from data_agent_backend.models.common import BackendModel, JsonDict
from data_agent_backend.services.factory import BackendServices

from .deps import get_backend_services


router = APIRouter(prefix="/analysis-context", tags=["analysis-context"])


class SearchPayload(BackendModel):
    query: str
    limit: int = 10


class ContextPayload(BackendModel):
    question: str
    limit: int = 10


class TableProfilePayload(BackendModel):
    schema_name: str | None = None
    table_name: str
    row_count: int | None = None
    table_type: str = "unknown"
    description: str | None = None
    primary_date_column: str | None = None
    metadata: JsonDict = {}


class ColumnProfilePayload(BackendModel):
    schema_name: str | None = None
    table_name: str
    column_name: str
    semantic_type: str | None = None
    description: str | None = None
    null_ratio: float | None = None
    distinct_count: int | None = None
    sample_values: list[str] = []
    metadata: JsonDict = {}


class MetricPayload(BackendModel):
    name: str
    description: str | None = None
    expression: str
    recommended_table: str | None = None
    filters: list[str] = []
    dimensions: list[str] = []
    metadata: JsonDict = {}


class BusinessTermPayload(BackendModel):
    term: str
    description: str | None = None
    related_tables: list[str] = []
    related_columns: list[str] = []
    related_metrics: list[str] = []
    metadata: JsonDict = {}


class MartPayload(BackendModel):
    table_name: str
    description: str | None = None
    grain: str | None = None
    date_column: str | None = None
    priority: int = 0
    related_metrics: list[str] = []
    metadata: JsonDict = {}


class JoinPathPayload(BackendModel):
    left_table: str
    right_table: str
    join_condition: str
    relationship_type: str | None = None
    confidence: float = 0.0
    metadata: JsonDict = {}


class JoinPathSearchPayload(BackendModel):
    table_names: list[str]


class ProfileDatasourcePayload(BackendModel):
    table_names: list[str] | None = None
    sample_limit: int = 20


class SemanticSeedPayload(BackendModel):
    seed: JsonDict


@router.post("/{datasource_id}/catalog-search")
def catalog_search(datasource_id: str, payload: SearchPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_catalog_search_impl(datasource_id=datasource_id, query=payload.query, limit=payload.limit, services=services)
    )


@router.post("/{datasource_id}/semantic-search")
def semantic_search(datasource_id: str, payload: SearchPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_semantic_search_impl(datasource_id=datasource_id, query=payload.query, limit=payload.limit, services=services)
    )


@router.post("/{datasource_id}/context")
def build_context(datasource_id: str, payload: ContextPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_build_context_impl(datasource_id=datasource_id, question=payload.question, limit=payload.limit, services=services)
    )


@router.post("/{datasource_id}/profile")
def profile_datasource(datasource_id: str, payload: ProfileDatasourcePayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_profile_datasource_impl(
            datasource_id=datasource_id,
            table_names=payload.table_names,
            sample_limit=payload.sample_limit,
            services=services,
        )
    )


@router.post("/{datasource_id}/semantic-seed")
def load_semantic_seed(datasource_id: str, payload: SemanticSeedPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(analysis_load_semantic_seed_impl(datasource_id=datasource_id, seed=payload.seed, services=services))


@router.post("/{datasource_id}/table-profiles")
def upsert_table_profile(datasource_id: str, payload: TableProfilePayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_upsert_table_profile_impl(
            datasource_id=datasource_id,
            table_name=payload.table_name,
            schema_name=payload.schema_name,
            row_count=payload.row_count,
            table_type=payload.table_type,
            description=payload.description,
            primary_date_column=payload.primary_date_column,
            metadata=payload.metadata,
            services=services,
        )
    )


@router.get("/{datasource_id}/table-profiles/{table_name}")
def get_table_profile(datasource_id: str, table_name: str, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(analysis_get_table_profile_impl(datasource_id=datasource_id, table_name=table_name, services=services))


@router.post("/{datasource_id}/column-profiles")
def upsert_column_profile(datasource_id: str, payload: ColumnProfilePayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_upsert_column_profile_impl(
            datasource_id=datasource_id,
            table_name=payload.table_name,
            column_name=payload.column_name,
            schema_name=payload.schema_name,
            semantic_type=payload.semantic_type,
            description=payload.description,
            null_ratio=payload.null_ratio,
            distinct_count=payload.distinct_count,
            sample_values=payload.sample_values,
            metadata=payload.metadata,
            services=services,
        )
    )


@router.get("/{datasource_id}/column-profiles/{table_name}/{column_name}")
def get_column_profile(datasource_id: str, table_name: str, column_name: str, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_get_column_profile_impl(
            datasource_id=datasource_id,
            table_name=table_name,
            column_name=column_name,
            services=services,
        )
    )


@router.post("/{datasource_id}/metrics")
def upsert_metric(datasource_id: str, payload: MetricPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_upsert_metric_impl(
            datasource_id=datasource_id,
            name=payload.name,
            description=payload.description,
            expression=payload.expression,
            recommended_table=payload.recommended_table,
            filters=payload.filters,
            dimensions=payload.dimensions,
            metadata=payload.metadata,
            services=services,
        )
    )


@router.post("/{datasource_id}/business-terms")
def upsert_business_term(datasource_id: str, payload: BusinessTermPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_upsert_business_term_impl(
            datasource_id=datasource_id,
            term=payload.term,
            description=payload.description,
            related_tables=payload.related_tables,
            related_columns=payload.related_columns,
            related_metrics=payload.related_metrics,
            metadata=payload.metadata,
            services=services,
        )
    )


@router.post("/{datasource_id}/marts")
def upsert_mart(datasource_id: str, payload: MartPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_upsert_mart_impl(
            datasource_id=datasource_id,
            table_name=payload.table_name,
            description=payload.description,
            grain=payload.grain,
            date_column=payload.date_column,
            priority=payload.priority,
            related_metrics=payload.related_metrics,
            metadata=payload.metadata,
            services=services,
        )
    )


@router.post("/{datasource_id}/join-paths")
def upsert_join_path(datasource_id: str, payload: JoinPathPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_upsert_join_path_impl(
            datasource_id=datasource_id,
            left_table=payload.left_table,
            right_table=payload.right_table,
            join_condition=payload.join_condition,
            relationship_type=payload.relationship_type,
            confidence=payload.confidence,
            metadata=payload.metadata,
            services=services,
        )
    )


@router.post("/{datasource_id}/join-paths/search")
def get_join_paths(datasource_id: str, payload: JoinPathSearchPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    return dump_result(
        analysis_get_join_paths_impl(datasource_id=datasource_id, table_names=payload.table_names, services=services)
    )
