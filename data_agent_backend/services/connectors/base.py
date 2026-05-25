from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from data_agent_backend.models.analysis_context import DatasourceProfileResult
from data_agent_backend.models.common import JsonDict
from data_agent_backend.models.datasources import DatasourceCatalogColumn, DatasourceDialectCapabilities


@dataclass(frozen=True)
class ConnectionConfig:
    host: str
    port: int
    database: str
    username: str
    password: str
    timeout_ms: int = 30_000


@dataclass(frozen=True)
class QueryRows:
    columns: list[str]
    rows: list[tuple]
    estimated_bytes: int = 0
    truncated_by_size: bool = False
    limit_reason: str | None = None


class DatasourceConnector(Protocol):
    def dialect_capabilities(self) -> DatasourceDialectCapabilities:
        ...

    def test_connection(self, config: ConnectionConfig) -> dict:
        ...

    def introspect(self, datasource_id: str, config: ConnectionConfig) -> list[DatasourceCatalogColumn]:
        ...

    def validate_query(self, query: str, row_limit: int) -> JsonDict:
        ...

    def execute_query(self, config: ConnectionConfig, query: str, row_limit: int) -> QueryRows:
        ...

    def profile_tables(
        self,
        config: ConnectionConfig,
        datasource_id: str,
        catalog: list[DatasourceCatalogColumn],
        table_names: list[str] | None = None,
        sample_limit: int = 5,
    ) -> DatasourceProfileResult:
        ...
