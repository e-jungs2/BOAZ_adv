from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from data_agent_backend.config import BackendConfig
from data_agent_backend.models.analysis_context import ColumnProfile, DatasourceProfileResult, TableProfile
from data_agent_backend.models.artifacts import ArtifactRegisterRequest, ArtifactType
from data_agent_backend.models.common import BackendError, JsonDict, utc_now_iso
from data_agent_backend.models.contexts import PolicyContext
from data_agent_backend.models.datasources import (
    DatasourceCatalogColumn,
    DatasourceCatalogSummary,
    DatasourceCatalogSummaryColumn,
    DatasourceCatalogSummaryTable,
    DatasourceCreateRequest,
    DatasourceDialectCapabilities,
    DatasourceKind,
    DatasourcePublic,
    DatasourceQueryResult,
    DatasourceRecord,
    DatasourceTestResult,
)
from data_agent_backend.models.ids import UUID4IdGenerator
from data_agent_backend.services.artifact_registry import ArtifactRegistry
from data_agent_backend.services.analysis_profile_store import AnalysisProfileStore
from data_agent_backend.services.connectors import ConnectionConfig, DatasourceConnector, MySQLConnector, QueryRows
from data_agent_backend.services.datasource_registry import DatasourceRegistry
from data_agent_backend.services.policy_engine import PolicyEngine
from data_agent_backend.services.semantic_registry import SemanticRegistry
from data_agent_backend.storage.sqlite import dumps_json, loads_json


class DatasourceService:
    def __init__(
        self,
        config: BackendConfig,
        registry: DatasourceRegistry,
        artifact_registry: ArtifactRegistry,
        policy_engine: PolicyEngine,
        profile_store: AnalysisProfileStore | None = None,
        semantic_registry: SemanticRegistry | None = None,
        connectors: dict[DatasourceKind, DatasourceConnector] | None = None,
        id_generator: UUID4IdGenerator | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.artifact_registry = artifact_registry
        self.policy_engine = policy_engine
        self.profile_store = profile_store
        self.semantic_registry = semantic_registry
        self.connectors = connectors or {DatasourceKind.mysql: MySQLConnector()}
        self.id_generator = id_generator or UUID4IdGenerator()

    def create_datasource(self, request: DatasourceCreateRequest, context: PolicyContext | None = None) -> DatasourcePublic:
        context = context or PolicyContext()
        self.policy_engine.enforce(
            "datasource.create",
            f"datasource:{request.kind.value}",
            self._safe_payload(request.model_dump(mode="json")),
            context,
        )
        if request.kind != DatasourceKind.mysql:
            raise BackendError("VALIDATION_ERROR", "Only MySQL datasources are supported in this MVP.", {"kind": request.kind.value})
        if not request.password:
            raise BackendError("VALIDATION_ERROR", "Datasource password is required.")
        datasource_id = self.id_generator.new_id("ds")
        now = utc_now_iso()
        secret_ref = f"datasource_{datasource_id}.json"
        self._write_secret(secret_ref, {"password": request.password, "created_at": now})
        record = DatasourceRecord(
            datasource_id=datasource_id,
            name=request.name,
            kind=request.kind,
            host=request.host,
            port=request.port,
            database=request.database,
            username=request.username,
            secret_ref=secret_ref,
            metadata=request.metadata,
            created_at=now,
            updated_at=now,
        )
        return self.registry.create(record).public()

    def test_datasource(self, datasource_id: str, context: PolicyContext | None = None) -> DatasourceTestResult:
        context = context or PolicyContext()
        record = self._get_record(datasource_id, context, action="datasource.test")
        metadata = self._connector(record).test_connection(self._connection_config(record))
        return DatasourceTestResult(datasource_id=datasource_id, ok=True, message="Connection succeeded.", metadata=metadata)

    def list_datasources(self, context: PolicyContext | None = None) -> list[DatasourcePublic]:
        self.policy_engine.enforce("datasource.read", "datasources", {}, context or PolicyContext())
        return [record.public() for record in self.registry.list()]

    def refresh_catalog(self, datasource_id: str, context: PolicyContext | None = None) -> list[DatasourceCatalogColumn]:
        context = context or PolicyContext()
        record = self._get_record(datasource_id, context, action="datasource.catalog.refresh")
        columns = self._connector(record).introspect(datasource_id, self._connection_config(record))
        return self.registry.replace_catalog(datasource_id, columns)

    def get_catalog(self, datasource_id: str, table_name: str | None = None, context: PolicyContext | None = None) -> list[DatasourceCatalogColumn]:
        self._get_record(datasource_id, context or PolicyContext(), action="datasource.read")
        return self.registry.get_catalog(datasource_id, table_name)

    def get_catalog_summary(self, datasource_id: str, context: PolicyContext | None = None) -> DatasourceCatalogSummary:
        record = self._get_record(datasource_id, context or PolicyContext(), action="datasource.read")
        columns = self.registry.get_catalog(datasource_id)
        grouped: dict[tuple[str | None, str], list[DatasourceCatalogColumn]] = {}
        for column in columns:
            grouped.setdefault((column.schema_name, column.table_name), []).append(column)

        tables: list[DatasourceCatalogSummaryTable] = []
        for (schema_name, table_name), table_columns in sorted(grouped.items(), key=lambda item: ((item[0][0] or ""), item[0][1])):
            sorted_columns = sorted(table_columns, key=lambda item: item.ordinal_position or 0)
            tables.append(
                DatasourceCatalogSummaryTable(
                    schema_name=schema_name,
                    table_name=table_name,
                    column_count=len(sorted_columns),
                    columns=[
                        DatasourceCatalogSummaryColumn(
                            name=column.column_name,
                            data_type=column.data_type,
                            nullable=column.nullable,
                            ordinal_position=column.ordinal_position,
                        )
                        for column in sorted_columns
                    ],
                    refreshed_at=sorted_columns[0].refreshed_at if sorted_columns else None,
                )
            )

        return DatasourceCatalogSummary(
            datasource_id=datasource_id,
            table_count=len(tables),
            total_column_count=len(columns),
            tables=tables,
            dialect_capabilities=self._dialect_capabilities_for_record(record),
            usage_notes=[
                "Use datasource_query with a single read-only SELECT statement.",
                "Inspect table and column names from this summary before writing SQL.",
                "Prefer explicit column lists and filters before broad SELECT queries.",
            ],
        )

    def get_dialect_capabilities(self, datasource_id: str, context: PolicyContext | None = None) -> DatasourceDialectCapabilities:
        record = self._get_record(datasource_id, context or PolicyContext(), action="datasource.read")
        return self._dialect_capabilities_for_record(record)

    def profile_datasource(
        self,
        datasource_id: str,
        table_names: list[str] | None = None,
        sample_limit: int = 20,
        context: PolicyContext | None = None,
    ) -> DatasourceProfileResult:
        context = context or PolicyContext()
        record = self._get_record(datasource_id, context, action="datasource.profile")
        catalog = self.registry.get_catalog(datasource_id)
        selected_catalog = self._filter_catalog(catalog, table_names)
        connector = self._connector(record)
        if hasattr(connector, "profile_tables"):
            result = connector.profile_tables(self._connection_config(record), datasource_id, selected_catalog, table_names, sample_limit)
        else:
            result = self._catalog_profile(datasource_id, selected_catalog)
        if self.profile_store is not None:
            for table_profile in result.table_profiles:
                self.profile_store.upsert_table_profile(table_profile)
            for column_profile in result.column_profiles:
                self.profile_store.upsert_column_profile(column_profile)
        if self.semantic_registry is not None:
            for mart in result.marts:
                self.semantic_registry.upsert_mart(mart)
            for join_path in result.join_paths:
                self.semantic_registry.upsert_join_path(join_path)
        return result

    def query_datasource(
        self,
        datasource_id: str,
        query: str,
        run_id: str,
        row_limit: int | None = None,
        context: PolicyContext | None = None,
    ) -> DatasourceQueryResult:
        context = context or PolicyContext(run_id=run_id)
        if context.run_id is None:
            context = context.model_copy(update={"run_id": run_id})
        row_limit = row_limit or self.config.default_sql_row_limit
        record = self._get_record(datasource_id, context, action="datasource.query", payload={"row_limit": row_limit})
        connector = self._connector(record)
        validation = connector.validate_query(query, row_limit)
        decision = self.policy_engine.evaluate(
            "datasource.query",
            f"datasource:{datasource_id}",
            {
                "datasource_id": datasource_id,
                "kind": record.kind.value,
                "row_limit": row_limit,
                "max_row_limit": self.config.max_sql_row_limit_without_approval,
                **validation,
            },
            context,
        )
        if not decision.allowed:
            code = "APPROVAL_REQUIRED" if decision.requires_approval else "POLICY_BLOCKED"
            raise BackendError(code, decision.reason, {"decision_id": decision.decision_id, **self._validation_error_details(validation)})

        query_artifact = self.artifact_registry.register_artifact(
            ArtifactRegisterRequest(
                run_id=run_id,
                type=ArtifactType.sql_query,
                content_text=query,
                filename="query.sql",
                created_by_tool=context.tool_name or "datasource_query",
                thread_id=context.thread_id,
                project_id=context.project_id,
                metadata={"datasource_id": datasource_id, "datasource_kind": record.kind.value, "database": record.database, "row_limit": row_limit},
            ),
            context,
        )
        try:
            result = connector.execute_query(self._connection_config(record), query, row_limit)
            csv_text = self._rows_to_csv(result.columns, result.rows)
            estimated_bytes = len(csv_text.encode("utf-8"))
            if estimated_bytes > self.config.datasource_max_result_bytes:
                raise BackendError(
                    "RESULT_TOO_LARGE",
                    "Datasource query result is too large.",
                    {
                        "max_result_bytes": self.config.datasource_max_result_bytes,
                        "estimated_bytes": estimated_bytes,
                        "retryable": True,
                        "suggestion": "Select fewer columns, add filters, aggregate results, or lower row_limit.",
                        "query_artifact_id": query_artifact.artifact_id,
                    },
                )
        except BackendError as exc:
            if exc.code in {"DATASOURCE_QUERY_TIMEOUT", "DATASOURCE_QUERY_ERROR", "DATASOURCE_CONNECTION_ERROR"}:
                details = dict(exc.details)
                details.setdefault("datasource_id", datasource_id)
                details.setdefault("query_artifact_id", query_artifact.artifact_id)
                raise BackendError(exc.code, exc.message, details) from exc
            raise
        sample_rows = [self._preview_row(result.columns, row) for row in result.rows[:5]]
        result_artifact = self.artifact_registry.register_artifact(
            ArtifactRegisterRequest(
                run_id=run_id,
                type=ArtifactType.sql_result,
                content_text=csv_text,
                filename="result.csv",
                created_by_tool=context.tool_name or "datasource_query",
                thread_id=context.thread_id,
                project_id=context.project_id,
                parent_ids=[query_artifact.artifact_id],
                lineage_edge_type="query_result_of",
                metadata={
                    "datasource_id": datasource_id,
                    "datasource_kind": record.kind.value,
                    "database": record.database,
                    "row_limit": row_limit,
                    "returned_rows": len(result.rows),
                    "estimated_bytes": estimated_bytes,
                },
                preview={"row_count": len(result.rows), "columns": result.columns, "sample_rows": sample_rows},
            ),
            context,
        )
        return DatasourceQueryResult(artifact_ref=result_artifact.ref(), columns=result.columns, row_count=len(result.rows), sample_rows=sample_rows)

    def validate_mysql_sql(self, query: str, row_limit: int) -> JsonDict:
        return MySQLConnector().validate_query(query, row_limit)

    def _get_record(self, datasource_id: str, context: PolicyContext, action: str, payload: JsonDict | None = None) -> DatasourceRecord:
        self.policy_engine.enforce(action, f"datasource:{datasource_id}", payload or {}, context)
        return self.registry.get(datasource_id)

    def _connector(self, record: DatasourceRecord) -> DatasourceConnector:
        connector = self.connectors.get(record.kind)
        if connector is None:
            raise BackendError("VALIDATION_ERROR", "Datasource kind is not supported.", {"kind": record.kind.value})
        return connector

    def _dialect_capabilities_for_record(self, record: DatasourceRecord) -> DatasourceDialectCapabilities:
        connector = self._connector(record)
        if hasattr(connector, "dialect_capabilities"):
            return connector.dialect_capabilities()
        if record.kind == DatasourceKind.mysql:
            return MySQLConnector().dialect_capabilities()
        return DatasourceDialectCapabilities(dialect=record.kind.value)

    def _connection_config(self, record: DatasourceRecord) -> ConnectionConfig:
        secret = self._read_secret(record.secret_ref)
        password = str(secret.get("password") or "")
        if not password:
            raise BackendError("VALIDATION_ERROR", "Datasource secret is missing a password.", {"datasource_id": record.datasource_id})
        return ConnectionConfig(
            host=record.host,
            port=record.port,
            database=record.database,
            username=record.username,
            password=password,
            timeout_ms=self.config.datasource_query_timeout_ms,
        )

    def _write_secret(self, secret_ref: str, payload: JsonDict) -> None:
        path = self._secret_path(secret_ref)
        path.write_text(dumps_json(payload), encoding="utf-8")

    def _read_secret(self, secret_ref: str) -> JsonDict:
        path = self._secret_path(secret_ref)
        if not path.exists():
            raise BackendError("NOT_FOUND", "Datasource secret was not found.", {"secret_ref": secret_ref})
        return loads_json(path.read_text(encoding="utf-8"))

    def _secret_path(self, secret_ref: str) -> Path:
        if "/" in secret_ref or "\\" in secret_ref:
            raise BackendError("VALIDATION_ERROR", "Invalid secret reference.")
        path = (self.config.secrets_dir / secret_ref).resolve()
        base = self.config.secrets_dir.resolve()
        if base not in path.parents and path != base:
            raise BackendError("VALIDATION_ERROR", "Invalid secret reference.")
        return path

    def _safe_payload(self, payload: JsonDict) -> JsonDict:
        safe = dict(payload)
        safe.pop("password", None)
        return safe

    def _filter_catalog(self, catalog: list[DatasourceCatalogColumn], table_names: list[str] | None) -> list[DatasourceCatalogColumn]:
        if not table_names:
            return catalog
        allowed = set(table_names)
        return [column for column in catalog if column.table_name in allowed]

    def _catalog_profile(self, datasource_id: str, catalog: list[DatasourceCatalogColumn]) -> DatasourceProfileResult:
        table_profiles: list[TableProfile] = []
        column_profiles: list[ColumnProfile] = []
        grouped: dict[str, list[DatasourceCatalogColumn]] = {}
        for column in catalog:
            grouped.setdefault(column.table_name, []).append(column)
        for table_name, columns in sorted(grouped.items()):
            primary_date_column = self._primary_date_column(columns)
            table_profiles.append(
                TableProfile(
                    datasource_id=datasource_id,
                    schema_name=columns[0].schema_name if columns else None,
                    table_name=table_name,
                    table_type="raw",
                    primary_date_column=primary_date_column,
                    metadata={"profile_source": "catalog"},
                )
            )
            for column in columns:
                column_profiles.append(
                    ColumnProfile(
                        datasource_id=datasource_id,
                        schema_name=column.schema_name,
                        table_name=column.table_name,
                        column_name=column.column_name,
                        semantic_type=self._semantic_type_for_column(column),
                        metadata={"profile_source": "catalog"},
                    )
                )
        return DatasourceProfileResult(
            datasource_id=datasource_id,
            table_profiles=table_profiles,
            column_profiles=column_profiles,
            usage_notes=["Profiles were inferred from catalog only; row counts and sample values are unavailable."],
        )

    def _primary_date_column(self, columns: list[DatasourceCatalogColumn]) -> str | None:
        for column in columns:
            if self._semantic_type_for_column(column) in {"date", "datetime", "datetime_string"}:
                return column.column_name
        return None

    def _semantic_type_for_column(self, column: DatasourceCatalogColumn) -> str | None:
        name = column.column_name.lower()
        data_type = column.data_type.lower()
        if "date" in data_type and "time" in data_type:
            return "datetime"
        if "timestamp" in data_type or "datetime" in data_type:
            return "datetime"
        if "date" in data_type:
            return "date"
        if any(token in name for token in ("timestamp", "datetime")):
            return "datetime_string" if any(token in data_type for token in ("char", "text", "varchar")) else "datetime"
        if "date" in name:
            return "date_string" if any(token in data_type for token in ("char", "text", "varchar")) else "date"
        if any(token in name for token in ("status", "type", "category", "code")):
            return "categorical"
        return None

    def _rows_to_csv(self, columns: list[str], rows: list[tuple]) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(columns)
        writer.writerows([[self._csv_cell(value) for value in row] for row in rows])
        return out.getvalue()

    def _preview_row(self, columns: list[str], row: tuple) -> JsonDict:
        return {column: self._json_cell(value) for column, value in zip(columns, row)}

    def _json_cell(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return self._truncate_preview_value(value)
        if isinstance(value, Decimal):
            return float(value)
        try:
            json.dumps(value)
            return self._truncate_preview_value(value)
        except TypeError:
            return self._truncate_preview_value(str(value))

    def _csv_cell(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        return value

    def _validation_error_details(self, validation: JsonDict) -> JsonDict:
        if not validation.get("blocked"):
            return {}
        return {
            key: validation[key]
            for key in ("reason_type", "blocked_keywords", "suggestion")
            if key in validation
        }

    def _truncate_preview_value(self, value: Any) -> Any:
        if isinstance(value, str) and len(value) > self.config.datasource_max_cell_preview_chars:
            return value[: self.config.datasource_max_cell_preview_chars] + "...[truncated]"
        return value
