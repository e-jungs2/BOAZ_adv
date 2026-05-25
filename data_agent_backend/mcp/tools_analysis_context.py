from __future__ import annotations

from typing import Any

from data_agent_backend.mcp.deps import get_services, result_wrap
from data_agent_backend.models.analysis_context import BusinessTerm, ColumnProfile, JoinPath, MartDefinition, MetricDefinition, TableProfile
from data_agent_backend.models.common import JsonDict
from data_agent_backend.models.tool_results import ToolResult
from data_agent_backend.services.factory import BackendServices


def analysis_catalog_search(datasource_id: str, query: str, limit: int = 10) -> ToolResult:
    return analysis_catalog_search_impl(
        datasource_id=datasource_id,
        query=query,
        limit=limit,
        services=get_services(),
    )


def analysis_catalog_search_impl(*, datasource_id: str, query: str, limit: int = 10, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.analysis_context_service.catalog_search(datasource_id, query, limit))


def analysis_get_table_profile(datasource_id: str, table_name: str, schema_name: str | None = None) -> ToolResult:
    return analysis_get_table_profile_impl(
        datasource_id=datasource_id,
        table_name=table_name,
        schema_name=schema_name,
        services=get_services(),
    )


def analysis_get_table_profile_impl(
    *, datasource_id: str, table_name: str, schema_name: str | None = None, services: BackendServices
) -> ToolResult:
    return result_wrap(lambda: services.analysis_context_service.get_table_profile(datasource_id, table_name, schema_name))


def analysis_get_column_profile(
    datasource_id: str,
    table_name: str,
    column_name: str,
    schema_name: str | None = None,
) -> ToolResult:
    return analysis_get_column_profile_impl(
        datasource_id=datasource_id,
        table_name=table_name,
        column_name=column_name,
        schema_name=schema_name,
        services=get_services(),
    )


def analysis_get_column_profile_impl(
    *,
    datasource_id: str,
    table_name: str,
    column_name: str,
    schema_name: str | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(
        lambda: services.analysis_context_service.get_column_profile(datasource_id, table_name, column_name, schema_name)
    )


def analysis_semantic_search(datasource_id: str, query: str, limit: int = 10) -> ToolResult:
    return analysis_semantic_search_impl(
        datasource_id=datasource_id,
        query=query,
        limit=limit,
        services=get_services(),
    )


def analysis_semantic_search_impl(*, datasource_id: str, query: str, limit: int = 10, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.analysis_context_service.semantic_search(datasource_id, query, limit))


def analysis_get_join_paths(datasource_id: str, table_names: list[str]) -> ToolResult:
    return analysis_get_join_paths_impl(datasource_id=datasource_id, table_names=table_names, services=get_services())


def analysis_get_join_paths_impl(*, datasource_id: str, table_names: list[str], services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.analysis_context_service.get_join_paths(datasource_id, table_names))


def analysis_build_context(datasource_id: str, question: str, limit: int = 10) -> ToolResult:
    return analysis_build_context_impl(
        datasource_id=datasource_id,
        question=question,
        limit=limit,
        services=get_services(),
    )


def analysis_build_context_impl(*, datasource_id: str, question: str, limit: int = 10, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.analysis_context_service.build_analysis_context(datasource_id, question, limit))


def analysis_profile_datasource(
    datasource_id: str,
    table_names: list[str] | None = None,
    sample_limit: int = 20,
) -> ToolResult:
    return analysis_profile_datasource_impl(
        datasource_id=datasource_id,
        table_names=table_names,
        sample_limit=sample_limit,
        services=get_services(),
    )


def analysis_profile_datasource_impl(
    *,
    datasource_id: str,
    table_names: list[str] | None = None,
    sample_limit: int = 20,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.datasource_service.profile_datasource(datasource_id, table_names, sample_limit))


def analysis_load_semantic_seed(datasource_id: str, seed: dict[str, Any]) -> ToolResult:
    return analysis_load_semantic_seed_impl(datasource_id=datasource_id, seed=seed, services=get_services())


def analysis_load_semantic_seed_impl(*, datasource_id: str, seed: dict[str, Any], services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.semantic_registry.load_seed(datasource_id, seed))


def analysis_upsert_table_profile(
    datasource_id: str,
    table_name: str,
    schema_name: str | None = None,
    row_count: int | None = None,
    table_type: str = "unknown",
    description: str | None = None,
    primary_date_column: str | None = None,
    metadata: JsonDict | None = None,
) -> ToolResult:
    return analysis_upsert_table_profile_impl(
        datasource_id=datasource_id,
        table_name=table_name,
        schema_name=schema_name,
        row_count=row_count,
        table_type=table_type,
        description=description,
        primary_date_column=primary_date_column,
        metadata=metadata,
        services=get_services(),
    )


def analysis_upsert_table_profile_impl(
    *,
    datasource_id: str,
    table_name: str,
    schema_name: str | None = None,
    row_count: int | None = None,
    table_type: str = "unknown",
    description: str | None = None,
    primary_date_column: str | None = None,
    metadata: JsonDict | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(
        lambda: services.analysis_profile_store.upsert_table_profile(
            TableProfile(
                datasource_id=datasource_id,
                schema_name=schema_name,
                table_name=table_name,
                row_count=row_count,
                table_type=table_type,
                description=description,
                primary_date_column=primary_date_column,
                metadata=metadata or {},
            )
        )
    )


def analysis_upsert_column_profile(
    datasource_id: str,
    table_name: str,
    column_name: str,
    schema_name: str | None = None,
    semantic_type: str | None = None,
    description: str | None = None,
    null_ratio: float | None = None,
    distinct_count: int | None = None,
    sample_values: list[str] | None = None,
    metadata: JsonDict | None = None,
) -> ToolResult:
    return analysis_upsert_column_profile_impl(
        datasource_id=datasource_id,
        table_name=table_name,
        column_name=column_name,
        schema_name=schema_name,
        semantic_type=semantic_type,
        description=description,
        null_ratio=null_ratio,
        distinct_count=distinct_count,
        sample_values=sample_values,
        metadata=metadata,
        services=get_services(),
    )


def analysis_upsert_column_profile_impl(
    *,
    datasource_id: str,
    table_name: str,
    column_name: str,
    schema_name: str | None = None,
    semantic_type: str | None = None,
    description: str | None = None,
    null_ratio: float | None = None,
    distinct_count: int | None = None,
    sample_values: list[str] | None = None,
    metadata: JsonDict | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(
        lambda: services.analysis_profile_store.upsert_column_profile(
            ColumnProfile(
                datasource_id=datasource_id,
                schema_name=schema_name,
                table_name=table_name,
                column_name=column_name,
                semantic_type=semantic_type,
                description=description,
                null_ratio=null_ratio,
                distinct_count=distinct_count,
                sample_values=sample_values or [],
                metadata=metadata or {},
            )
        )
    )


def analysis_upsert_metric(
    datasource_id: str,
    name: str,
    expression: str,
    description: str | None = None,
    recommended_table: str | None = None,
    filters: list[str] | None = None,
    dimensions: list[str] | None = None,
    metadata: JsonDict | None = None,
) -> ToolResult:
    return analysis_upsert_metric_impl(
        datasource_id=datasource_id,
        name=name,
        expression=expression,
        description=description,
        recommended_table=recommended_table,
        filters=filters,
        dimensions=dimensions,
        metadata=metadata,
        services=get_services(),
    )


def analysis_upsert_metric_impl(
    *,
    datasource_id: str,
    name: str,
    expression: str,
    description: str | None = None,
    recommended_table: str | None = None,
    filters: list[str] | None = None,
    dimensions: list[str] | None = None,
    metadata: JsonDict | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(
        lambda: services.semantic_registry.upsert_metric(
            MetricDefinition(
                datasource_id=datasource_id,
                name=name,
                description=description,
                expression=expression,
                recommended_table=recommended_table,
                filters=filters or [],
                dimensions=dimensions or [],
                metadata=metadata or {},
            )
        )
    )


def analysis_upsert_business_term(
    datasource_id: str,
    term: str,
    description: str | None = None,
    related_tables: list[str] | None = None,
    related_columns: list[str] | None = None,
    related_metrics: list[str] | None = None,
    metadata: JsonDict | None = None,
) -> ToolResult:
    return analysis_upsert_business_term_impl(
        datasource_id=datasource_id,
        term=term,
        description=description,
        related_tables=related_tables,
        related_columns=related_columns,
        related_metrics=related_metrics,
        metadata=metadata,
        services=get_services(),
    )


def analysis_upsert_business_term_impl(
    *,
    datasource_id: str,
    term: str,
    description: str | None = None,
    related_tables: list[str] | None = None,
    related_columns: list[str] | None = None,
    related_metrics: list[str] | None = None,
    metadata: JsonDict | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(
        lambda: services.semantic_registry.upsert_business_term(
            BusinessTerm(
                datasource_id=datasource_id,
                term=term,
                description=description,
                related_tables=related_tables or [],
                related_columns=related_columns or [],
                related_metrics=related_metrics or [],
                metadata=metadata or {},
            )
        )
    )


def analysis_upsert_mart(
    datasource_id: str,
    table_name: str,
    description: str | None = None,
    grain: str | None = None,
    date_column: str | None = None,
    priority: int = 0,
    related_metrics: list[str] | None = None,
    metadata: JsonDict | None = None,
) -> ToolResult:
    return analysis_upsert_mart_impl(
        datasource_id=datasource_id,
        table_name=table_name,
        description=description,
        grain=grain,
        date_column=date_column,
        priority=priority,
        related_metrics=related_metrics,
        metadata=metadata,
        services=get_services(),
    )


def analysis_upsert_mart_impl(
    *,
    datasource_id: str,
    table_name: str,
    description: str | None = None,
    grain: str | None = None,
    date_column: str | None = None,
    priority: int = 0,
    related_metrics: list[str] | None = None,
    metadata: JsonDict | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(
        lambda: services.semantic_registry.upsert_mart(
            MartDefinition(
                datasource_id=datasource_id,
                table_name=table_name,
                description=description,
                grain=grain,
                date_column=date_column,
                priority=priority,
                related_metrics=related_metrics or [],
                metadata=metadata or {},
            )
        )
    )


def analysis_upsert_join_path(
    datasource_id: str,
    left_table: str,
    right_table: str,
    join_condition: str,
    relationship_type: str | None = None,
    confidence: float = 0.0,
    metadata: JsonDict | None = None,
) -> ToolResult:
    return analysis_upsert_join_path_impl(
        datasource_id=datasource_id,
        left_table=left_table,
        right_table=right_table,
        join_condition=join_condition,
        relationship_type=relationship_type,
        confidence=confidence,
        metadata=metadata,
        services=get_services(),
    )


def analysis_upsert_join_path_impl(
    *,
    datasource_id: str,
    left_table: str,
    right_table: str,
    join_condition: str,
    relationship_type: str | None = None,
    confidence: float = 0.0,
    metadata: JsonDict | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(
        lambda: services.semantic_registry.upsert_join_path(
            JoinPath(
                datasource_id=datasource_id,
                left_table=left_table,
                right_table=right_table,
                join_condition=join_condition,
                relationship_type=relationship_type,
                confidence=confidence,
                metadata=metadata or {},
            )
        )
    )
