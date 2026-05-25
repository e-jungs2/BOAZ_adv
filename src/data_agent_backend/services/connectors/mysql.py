from __future__ import annotations

from collections.abc import Iterable

import sqlglot
from sqlglot import expressions as exp

from data_agent_backend.models.analysis_context import DatasourceProfileResult
from data_agent_backend.models.common import BackendError, JsonDict, utc_now_iso
from data_agent_backend.models.datasources import DatasourceCatalogColumn, DatasourceDialectCapabilities
from data_agent_backend.services.profile_inference import InferredTableProfile, ProfileInferenceEngine

from .base import ConnectionConfig, QueryRows


MYSQL_BLOCKED_SQL_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "CALL",
    "SET",
    "LOCK",
    "LOAD",
    "OUTFILE",
    "DUMPFILE",
    "GRANT",
    "REVOKE",
}

MYSQL_BLOCKED_EXPRESSIONS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.Set,
    exp.Transaction,
    exp.Grant,
    exp.Revoke,
    exp.LoadData,
)


class MySQLConnector:
    def dialect_capabilities(self) -> DatasourceDialectCapabilities:
        return DatasourceDialectCapabilities(
            dialect="mysql",
            date_diff_examples=[
                "TIMESTAMPDIFF(DAY, start_timestamp_col, end_timestamp_col)",
                "TIMESTAMPDIFF(HOUR, start_timestamp_col, end_timestamp_col) / 24.0",
            ],
            timestamp_cast_examples=[
                "CAST(timestamp_text_col AS DATETIME)",
                "STR_TO_DATE(timestamp_text_col, '%Y-%m-%d %H:%i:%s')",
            ],
            unsupported_functions=["julianday", "strftime"],
            identifier_quote="`",
            limit_style="LIMIT n",
            safe_query_notes=[
                "Use MySQL date/time functions for timestamp arithmetic.",
                "Do not use SQLite functions such as julianday or strftime.",
                "Use explicit schema-qualified table names when the catalog includes schema names.",
            ],
        )

    def test_connection(self, config: ConnectionConfig) -> dict:
        try:
            engine = self._engine(config)
            try:
                with engine.connect() as conn:
                    value = conn.execute(self._text("SELECT 1")).scalar()
                return {"server_reachable": True, "select_1": value}
            finally:
                engine.dispose()
        except Exception as exc:
            raise BackendError("CONNECTION_FAILED", "MySQL connection test failed.", {"type": type(exc).__name__, "message": str(exc)}) from exc

    def introspect(self, datasource_id: str, config: ConnectionConfig) -> list[DatasourceCatalogColumn]:
        engine = self._engine(config)
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    self._text(
                        """
                        SELECT
                            table_schema,
                            table_name,
                            column_name,
                            data_type,
                            is_nullable,
                            ordinal_position
                        FROM information_schema.columns
                        WHERE table_schema = :database
                        ORDER BY table_name, ordinal_position
                        """
                    ),
                    {"database": config.database},
                )
                refreshed_at = utc_now_iso()
                return [
                    DatasourceCatalogColumn(
                        datasource_id=datasource_id,
                        schema_name=row[0],
                        table_name=row[1],
                        column_name=row[2],
                        data_type=row[3],
                        nullable=str(row[4]).upper() == "YES",
                        ordinal_position=row[5],
                        refreshed_at=refreshed_at,
                    )
                    for row in result.fetchall()
                ]
        finally:
            engine.dispose()

    def execute_query(self, config: ConnectionConfig, query: str, row_limit: int) -> QueryRows:
        wrapped = f"SELECT * FROM ({query.rstrip().rstrip(';')}) AS data_agent_subquery LIMIT {int(row_limit)}"
        try:
            engine = self._engine(config)
        except BackendError:
            raise
        except Exception as exc:
            raise self._connection_error(exc) from exc
        try:
            with engine.connect() as conn:
                conn.execute(self._text("SET SESSION MAX_EXECUTION_TIME = :timeout_ms"), {"timeout_ms": int(config.timeout_ms)})
                result = conn.execute(self._text(wrapped))
                rows = [tuple(row) for row in result.fetchall()]
                columns = list(result.keys())
                return QueryRows(columns=columns, rows=rows, estimated_bytes=self._estimate_rows_bytes(columns, rows))
        except Exception as exc:
            raise self._query_error(exc, config.timeout_ms) from exc
        finally:
            engine.dispose()

    def validate_query(self, query: str, row_limit: int) -> JsonDict:
        stripped = query.strip()
        if not stripped:
            return {"blocked": True, "reason": "SQL query is empty.", "reason_type": "empty_query", "suggestion": "Rewrite the query as a single read-only SELECT."}
        if self._has_multiple_statements(stripped):
            return {
                "blocked": True,
                "reason": "Multiple-statement SQL is blocked.",
                "reason_type": "multiple_statements",
                "suggestion": "Rewrite the query as a single read-only SELECT.",
            }
        upper_query = stripped.upper()
        for phrase in ("INTO OUTFILE", "INTO DUMPFILE", "LOAD_FILE"):
            if phrase in upper_query:
                return {
                    "blocked": True,
                    "reason": f"Blocked SQL construct: {phrase}.",
                    "reason_type": "blocked_construct",
                    "blocked_keywords": [phrase],
                    "suggestion": "Rewrite the query as a single read-only SELECT.",
                }
        upper_tokens = {token.upper() for token in stripped.replace(";", " ").replace("\n", " ").replace("\t", " ").split()}
        blocked = sorted(upper_tokens & MYSQL_BLOCKED_SQL_KEYWORDS)
        if blocked:
            return {
                "blocked": True,
                "reason": f"Blocked SQL keyword(s): {', '.join(blocked)}.",
                "reason_type": "blocked_keywords",
                "blocked_keywords": blocked,
                "suggestion": "Rewrite the query as a single read-only SELECT.",
            }
        try:
            parsed = sqlglot.parse_one(stripped, read="mysql")
        except Exception as exc:
            return {
                "blocked": True,
                "reason": f"SQL parse failed: {exc}",
                "reason_type": "parse_error",
                "suggestion": "Inspect the schema/catalog and correct table, column, or syntax issues.",
            }
        if not isinstance(parsed, (exp.Select, exp.Union, exp.With)):
            return {
                "blocked": True,
                "reason": "Only read-only SELECT queries are allowed.",
                "reason_type": "non_select_root",
                "suggestion": "Rewrite the query as a single read-only SELECT.",
            }
        blocked_expression = self._blocked_ast_expression(parsed)
        if blocked_expression is not None:
            return {
                "blocked": True,
                "reason": f"Blocked SQL expression: {blocked_expression}.",
                "reason_type": "blocked_ast_expression",
                "blocked_keywords": [blocked_expression],
                "suggestion": "Rewrite the query as a single read-only SELECT.",
            }
        if row_limit <= 0:
            return {"blocked": True, "reason": "row_limit must be positive.", "reason_type": "invalid_row_limit", "suggestion": "Use a positive row_limit."}
        return {"blocked": False}

    def profile_tables(
        self,
        config: ConnectionConfig,
        datasource_id: str,
        catalog: list[DatasourceCatalogColumn],
        table_names: list[str] | None = None,
        sample_limit: int = 20,
    ) -> DatasourceProfileResult:
        grouped: dict[str, list[DatasourceCatalogColumn]] = {}
        for column in catalog:
            grouped.setdefault(column.table_name, []).append(column)
        inference = ProfileInferenceEngine()
        inferred_tables: list[InferredTableProfile] = []
        sample_rows_by_table: dict[str, list[dict[str, object]]] = {}
        engine = self._engine(config)
        try:
            with engine.connect() as conn:
                row_counts = self._table_row_estimates(conn, config.database, list(grouped))
                for table_name, columns in sorted(grouped.items()):
                    try:
                        samples = self._sample_rows(conn, table_name, columns, sample_limit)
                    except Exception as exc:
                        samples = []
                        inferred = inference.infer_table(
                            datasource_id,
                            columns[0].schema_name if columns else config.database,
                            table_name,
                            columns,
                            samples,
                            sample_limit,
                            row_counts.get(table_name),
                        )
                        metadata = dict(inferred.table_profile.metadata)
                        profile_metadata = dict(metadata.get("profile", {}))
                        profile_metadata.update({"source": "mysql_sample", "skipped_reason": str(exc)})
                        metadata["profile"] = profile_metadata
                        inferred = InferredTableProfile(
                            table_profile=inferred.table_profile.model_copy(update={"metadata": metadata}),
                            column_profiles=inferred.column_profiles,
                            join_paths=inferred.join_paths,
                            marts=inferred.marts,
                        )
                    else:
                        inferred = inference.infer_table(
                            datasource_id,
                            columns[0].schema_name if columns else config.database,
                            table_name,
                            columns,
                            samples,
                            sample_limit,
                            row_counts.get(table_name),
                        )
                    inferred_tables.append(inferred)
                    sample_rows_by_table[table_name] = samples
        except Exception as exc:
            raise self._query_error(exc, config.timeout_ms) from exc
        finally:
            engine.dispose()
        join_paths = inference.infer_join_paths(datasource_id, inferred_tables, grouped, sample_rows_by_table, sample_limit)
        return DatasourceProfileResult(
            datasource_id=datasource_id,
            table_profiles=[item.table_profile for item in inferred_tables],
            column_profiles=[profile for item in inferred_tables for profile in item.column_profiles],
            join_paths=join_paths,
            marts=[mart for item in inferred_tables for mart in item.marts],
            usage_notes=[
                "Row counts are MySQL information_schema estimates.",
                "Sample values come from limited SELECT samples and should not be treated as exhaustive distributions.",
            ],
        )

    def _engine(self, config: ConnectionConfig):
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.engine import URL
        except Exception as exc:  # pragma: no cover - dependency guard
            raise BackendError("DEPENDENCY_MISSING", "SQLAlchemy and PyMySQL are required for MySQL datasources.") from exc

        url = URL.create(
            "mysql+pymysql",
            username=config.username,
            password=config.password,
            host=config.host,
            port=config.port,
            database=config.database,
        )
        timeout_seconds = max(1, int(config.timeout_ms / 1000))
        return create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": min(5, timeout_seconds), "read_timeout": timeout_seconds, "write_timeout": timeout_seconds},
        )

    def _text(self, sql: str):
        try:
            from sqlalchemy import text
        except Exception as exc:  # pragma: no cover - dependency guard
            raise BackendError("DEPENDENCY_MISSING", "SQLAlchemy is required for MySQL datasources.") from exc
        return text(sql)

    def _estimate_rows_bytes(self, columns: list[str], rows: Iterable[tuple]) -> int:
        total = sum(len(str(column).encode("utf-8")) for column in columns)
        for row in rows:
            total += sum(len(str(value).encode("utf-8")) if value is not None else 0 for value in row)
        return total

    def _table_row_estimates(self, conn, database: str, table_names: list[str]) -> dict[str, int | None]:
        if not table_names:
            return {}
        result = conn.execute(
            self._text(
                """
                SELECT table_name, table_rows
                FROM information_schema.tables
                WHERE table_schema = :database
                """
            ),
            {"database": database},
        )
        estimates = {str(row[0]): row[1] for row in result.fetchall()}
        return {table_name: estimates.get(table_name) for table_name in table_names}

    def _sample_rows(self, conn, table_name: str, columns: list[DatasourceCatalogColumn], sample_limit: int) -> list[dict[str, object]]:
        selected = columns[: min(len(columns), 20)]
        if not selected or sample_limit <= 0:
            return []
        column_sql = ", ".join(self._quote_identifier(column.column_name) for column in selected)
        table_sql = self._quote_identifier(table_name)
        result = conn.execute(self._text(f"SELECT {column_sql} FROM {table_sql} LIMIT {int(sample_limit)}"))
        keys = list(result.keys())
        return [dict(zip(keys, row)) for row in result.fetchall()]

    def _quote_identifier(self, value: str) -> str:
        return "`" + value.replace("`", "``") + "`"

    def _has_multiple_statements(self, query: str) -> bool:
        if ";" not in query:
            return False
        return query.rstrip().rstrip(";").find(";") != -1

    def _blocked_ast_expression(self, parsed: exp.Expression) -> str | None:
        for node in parsed.walk():
            if isinstance(node, MYSQL_BLOCKED_EXPRESSIONS):
                return type(node).__name__
        return None

    def _connection_error(self, exc: Exception) -> BackendError:
        return BackendError(
            "DATASOURCE_CONNECTION_ERROR",
            "Datasource connection failed.",
            {
                "type": type(exc).__name__,
                "retryable": True,
                "suggestion": "Check the datasource host, port, database, username, password, and network reachability.",
            },
        )

    def _query_error(self, exc: Exception, timeout_ms: int) -> BackendError:
        text = str(exc)
        lower = text.lower()
        details = {
            "type": type(exc).__name__,
            "retryable": False,
            "suggestion": "Inspect the schema/catalog and correct table, column, or syntax issues.",
        }
        sqlstate, db_error_code = self._db_error_parts(exc)
        if sqlstate is not None:
            details["sqlstate"] = sqlstate
        if db_error_code is not None:
            details["db_error_code"] = db_error_code
        for function_name in self.dialect_capabilities().unsupported_functions:
            if function_name.lower() in lower:
                details.update(
                    {
                        "reason_type": "unknown_function",
                        "unsupported_function": function_name,
                        "dialect": "mysql",
                        "suggestion": "Use MySQL TIMESTAMPDIFF(unit, start, end) for date differences instead of SQLite-style date functions.",
                    }
                )
                return BackendError("DATASOURCE_QUERY_ERROR", "Datasource query failed.", details)
        if "max_execution_time" in lower or "maximum statement execution time" in lower or "timed out" in lower or "timeout" in lower:
            details.update({"timeout_ms": timeout_ms, "retryable": True, "suggestion": "Add filters, aggregate earlier, or lower row_limit."})
            return BackendError("DATASOURCE_QUERY_TIMEOUT", "Datasource query timed out.", details)
        return BackendError("DATASOURCE_QUERY_ERROR", "Datasource query failed.", details)

    def _db_error_parts(self, exc: Exception) -> tuple[str | None, int | None]:
        orig = getattr(exc, "orig", exc)
        args = getattr(orig, "args", ())
        db_error_code = args[0] if args and isinstance(args[0], int) else None
        sqlstate = getattr(orig, "sqlstate", None)
        return sqlstate, db_error_code
