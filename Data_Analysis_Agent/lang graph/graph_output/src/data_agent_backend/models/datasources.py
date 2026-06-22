from __future__ import annotations

from enum import StrEnum

from data_agent_backend.models.artifacts import ArtifactRef

from .common import BackendModel, JsonDict


class DatasourceKind(StrEnum):
    mysql = "mysql"


class DatasourceCreateRequest(BackendModel):
    name: str
    kind: DatasourceKind = DatasourceKind.mysql
    host: str
    port: int = 3306
    database: str
    username: str
    password: str
    metadata: JsonDict = {}


class DatasourceRecord(BackendModel):
    datasource_id: str
    name: str
    kind: DatasourceKind
    host: str
    port: int
    database: str
    username: str
    secret_ref: str
    metadata: JsonDict = {}
    created_at: str
    updated_at: str

    def public(self) -> "DatasourcePublic":
        return DatasourcePublic(
            datasource_id=self.datasource_id,
            name=self.name,
            kind=self.kind,
            host=self.host,
            port=self.port,
            database=self.database,
            username=self.username,
            metadata=self.metadata,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class DatasourcePublic(BackendModel):
    datasource_id: str
    name: str
    kind: DatasourceKind
    host: str
    port: int
    database: str
    username: str
    metadata: JsonDict = {}
    created_at: str
    updated_at: str


class DatasourceCatalogColumn(BackendModel):
    datasource_id: str
    schema_name: str | None = None
    table_name: str
    column_name: str
    data_type: str
    nullable: bool
    ordinal_position: int | None = None
    metadata: JsonDict = {}
    refreshed_at: str | None = None


class DatasourceCatalogSummaryColumn(BackendModel):
    name: str
    data_type: str
    nullable: bool
    ordinal_position: int | None = None


class DatasourceCatalogSummaryTable(BackendModel):
    schema_name: str | None = None
    table_name: str
    column_count: int
    columns: list[DatasourceCatalogSummaryColumn]
    refreshed_at: str | None = None


class DatasourceDialectCapabilities(BackendModel):
    dialect: str
    date_diff_examples: list[str] = []
    timestamp_cast_examples: list[str] = []
    unsupported_functions: list[str] = []
    identifier_quote: str | None = None
    limit_style: str | None = None
    safe_query_notes: list[str] = []


class DatasourceCatalogSummary(BackendModel):
    datasource_id: str
    table_count: int
    total_column_count: int
    tables: list[DatasourceCatalogSummaryTable]
    dialect_capabilities: DatasourceDialectCapabilities | None = None
    usage_notes: list[str] = []


class DatasourceTestResult(BackendModel):
    datasource_id: str
    ok: bool
    message: str
    metadata: JsonDict = {}


class DatasourceQueryResult(BackendModel):
    artifact_ref: ArtifactRef
    columns: list[str]
    row_count: int
    sample_rows: list[JsonDict] = []
