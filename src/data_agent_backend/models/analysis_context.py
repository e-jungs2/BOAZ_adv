from __future__ import annotations

from .common import BackendModel, JsonDict
from .datasources import DatasourceDialectCapabilities


class CatalogSearchColumn(BackendModel):
    name: str
    data_type: str
    nullable: bool
    reason: str


class CatalogSearchMatch(BackendModel):
    datasource_id: str
    schema_name: str | None = None
    table_name: str
    columns: list[CatalogSearchColumn] = []
    reason: str
    confidence: float = 0.0
    warnings: list[str] = []


class CatalogSearchResult(BackendModel):
    datasource_id: str
    query: str
    matches: list[CatalogSearchMatch] = []


class TableProfile(BackendModel):
    datasource_id: str
    schema_name: str | None = None
    table_name: str
    row_count: int | None = None
    table_type: str = "unknown"
    description: str | None = None
    primary_date_column: str | None = None
    metadata: JsonDict = {}


class ColumnProfile(BackendModel):
    datasource_id: str
    schema_name: str | None = None
    table_name: str
    column_name: str
    semantic_type: str | None = None
    description: str | None = None
    null_ratio: float | None = None
    distinct_count: int | None = None
    sample_values: list[str] = []
    metadata: JsonDict = {}


class DatasourceProfileResult(BackendModel):
    datasource_id: str
    table_profiles: list[TableProfile] = []
    column_profiles: list[ColumnProfile] = []
    join_paths: list["JoinPath"] = []
    marts: list["MartDefinition"] = []
    usage_notes: list[str] = []


class MetricDefinition(BackendModel):
    datasource_id: str
    name: str
    description: str | None = None
    expression: str
    recommended_table: str | None = None
    filters: list[str] = []
    dimensions: list[str] = []
    metadata: JsonDict = {}


class BusinessTerm(BackendModel):
    datasource_id: str
    term: str
    description: str | None = None
    related_tables: list[str] = []
    related_columns: list[str] = []
    related_metrics: list[str] = []
    metadata: JsonDict = {}


class MartDefinition(BackendModel):
    datasource_id: str
    table_name: str
    description: str | None = None
    grain: str | None = None
    date_column: str | None = None
    priority: int = 0
    related_metrics: list[str] = []
    metadata: JsonDict = {}


class JoinPath(BackendModel):
    datasource_id: str
    left_table: str
    right_table: str
    join_condition: str
    relationship_type: str | None = None
    confidence: float = 0.0
    metadata: JsonDict = {}


class SemanticSearchResult(BackendModel):
    datasource_id: str
    query: str
    metrics: list[MetricDefinition] = []
    business_terms: list[BusinessTerm] = []
    marts: list[MartDefinition] = []


class SemanticSeedLoadResult(BackendModel):
    metrics: int = 0
    business_terms: int = 0
    marts: int = 0
    join_paths: int = 0


class RecommendedTable(BackendModel):
    table_name: str
    schema_name: str | None = None
    reason: str
    confidence: float = 0.0
    source: str = "catalog"
    warnings: list[str] = []


class RecommendedColumn(BackendModel):
    table_name: str
    column_name: str
    schema_name: str | None = None
    data_type: str
    semantic_type: str | None = None
    role: str
    reason: str
    confidence: float = 0.0


class JoinHint(BackendModel):
    left_table: str
    right_table: str
    join_condition: str
    relationship_type: str | None = None
    confidence: float = 0.0
    source: str = "catalog_inferred"
    warnings: list[str] = []


class TimeFilterHint(BackendModel):
    name: str
    table_name: str
    column_names: list[str]
    expression_hint: str
    dialect: str | None = None
    reason: str


class MetricHint(BackendModel):
    name: str
    expression_hint: str
    table_name: str | None = None
    column_names: list[str] = []
    reason: str
    source: str = "catalog"


class AnalysisWarning(BackendModel):
    code: str
    message: str
    severity: str = "info"
    details: JsonDict = {}


class AnalysisContext(BackendModel):
    datasource_id: str
    question: str
    catalog_matches: list[CatalogSearchMatch] = []
    table_profiles: list[TableProfile] = []
    column_profiles: list[ColumnProfile] = []
    metrics: list[MetricDefinition] = []
    business_terms: list[BusinessTerm] = []
    marts: list[MartDefinition] = []
    join_paths: list[JoinPath] = []
    dialect_capabilities: DatasourceDialectCapabilities | None = None
    query_guidance: list[str] = []
    usage_notes: list[str] = []
    recommended_tables: list[RecommendedTable] = []
    recommended_columns: list[RecommendedColumn] = []
    join_hints: list[JoinHint] = []
    time_filter_hints: list[TimeFilterHint] = []
    metric_hints: list[MetricHint] = []
    analysis_warnings: list[AnalysisWarning] = []
