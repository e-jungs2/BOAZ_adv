from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from data_agent_backend.api import create_app
from data_agent_backend.mcp.tools_datasources import (
    datasource_create_impl,
    datasource_get_catalog_summary_impl,
    datasource_list_impl,
    datasource_query_impl,
)
from data_agent_backend.models.artifacts import ArtifactType
from data_agent_backend.models.common import BackendError
from data_agent_backend.models.contexts import PolicyContext
from data_agent_backend.models.datasources import DatasourceCatalogColumn, DatasourceCreateRequest, DatasourceKind
from data_agent_backend.services.connectors import ConnectionConfig, MySQLConnector, QueryRows


class FakeMySQLConnector:
    def test_connection(self, config: ConnectionConfig) -> dict:
        return {"server_reachable": True, "database": config.database}

    def introspect(self, datasource_id: str, config: ConnectionConfig) -> list[DatasourceCatalogColumn]:
        return [
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name=config.database,
                table_name="orders",
                column_name="id",
                data_type="int",
                nullable=False,
                ordinal_position=1,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name=config.database,
                table_name="orders",
                column_name="amount",
                data_type="decimal",
                nullable=True,
                ordinal_position=2,
            ),
        ]

    def validate_query(self, query: str, row_limit: int) -> dict:
        return MySQLConnector().validate_query(query, row_limit)

    def execute_query(self, config: ConnectionConfig, query: str, row_limit: int) -> QueryRows:
        return QueryRows(columns=["id", "amount"], rows=[(1, 12.5), (2, 15.0)][:row_limit])


class LargeResultConnector(FakeMySQLConnector):
    def execute_query(self, config: ConnectionConfig, query: str, row_limit: int) -> QueryRows:
        return QueryRows(columns=["payload"], rows=[("x" * 200,)])


class TimeoutConnector(FakeMySQLConnector):
    def execute_query(self, config: ConnectionConfig, query: str, row_limit: int) -> QueryRows:
        raise BackendError(
            "DATASOURCE_QUERY_TIMEOUT",
            "Datasource query timed out.",
            {"timeout_ms": config.timeout_ms, "retryable": True, "suggestion": "Add filters, aggregate earlier, or lower row_limit."},
        )


class QueryErrorConnector(FakeMySQLConnector):
    def execute_query(self, config: ConnectionConfig, query: str, row_limit: int) -> QueryRows:
        raise BackendError(
            "DATASOURCE_QUERY_ERROR",
            "Datasource query failed.",
            {"db_error_code": 1054, "retryable": False, "suggestion": "Inspect the schema/catalog and correct table, column, or syntax issues."},
        )


class ConnectorValidationBlocksQuery(FakeMySQLConnector):
    def validate_query(self, query: str, row_limit: int) -> dict:
        return {
            "blocked": True,
            "reason": "Connector-specific validation blocked the query.",
            "reason_type": "connector_validation",
            "suggestion": "Use a query accepted by this datasource connector.",
        }


def install_fake_connector(services) -> None:
    services.datasource_service.connectors = {DatasourceKind.mysql: FakeMySQLConnector()}


def create_mysql_datasource(services) -> str:
    result = services.datasource_service.create_datasource(
        DatasourceCreateRequest(
            name="local mysql",
            host="127.0.0.1",
            database="analytics",
            username="reader",
            password="secret",
        ),
        PolicyContext(user_id="u1"),
    )
    return result.datasource_id


def test_datasource_create_stores_secret_outside_sqlite_and_hides_it(services):
    datasource_id = create_mysql_datasource(services)
    public = services.datasource_service.list_datasources()[0]
    assert public.datasource_id == datasource_id
    assert "secret" not in public.model_dump(mode="json")
    assert "secret_ref" not in public.model_dump(mode="json")

    row = services.sqlite.query_one("SELECT * FROM datasources WHERE datasource_id = ?", (datasource_id,))
    assert row is not None
    assert row["secret_ref"].startswith("datasource_")
    assert "secret" not in dict(row).values()
    secret_file = services.config.secrets_dir / row["secret_ref"]
    assert secret_file.exists()
    assert "secret" in secret_file.read_text(encoding="utf-8")


def test_mysql_sql_validation_allows_read_only_and_blocks_unsafe_queries(services):
    assert services.config.datasource_query_timeout_ms == 30_000
    assert services.config.datasource_max_result_bytes == 5_000_000
    validator = services.datasource_service.validate_mysql_sql
    for query in [
        "select 1 as x",
        "with x as (select 1 as id) select * from x",
        "select 1 as x union all select 2 as x",
    ]:
        assert validator(query, 100)["blocked"] is False

    for query in [
        "",
        "select 1; select 2",
        "delete from orders",
        "insert into orders values (1)",
        "drop table orders",
        "alter table orders add column x int",
        "set sql_safe_updates = 0",
        "call refresh_orders()",
        "load data infile 'x' into table orders",
        "select * from orders into outfile '/tmp/orders.csv'",
        "select load_file('/etc/passwd')",
    ]:
        assert validator(query, 100)["blocked"] is True

    assert validator("select 1", 0)["blocked"] is True


class FakeMySQLFunctionError(Exception):
    def __init__(self) -> None:
        self.orig = type("Orig", (), {"args": (1305, "FUNCTION olist.julianday does not exist")})()

    def __str__(self) -> str:
        return "(1305, 'FUNCTION olist.julianday does not exist')"


def test_mysql_query_error_classifies_unknown_function_with_dialect_hint():
    error = MySQLConnector()._query_error(FakeMySQLFunctionError(), timeout_ms=30_000)

    assert error.code == "DATASOURCE_QUERY_ERROR"
    assert error.details["reason_type"] == "unknown_function"
    assert error.details["unsupported_function"] == "julianday"
    assert error.details["dialect"] == "mysql"
    assert "TIMESTAMPDIFF" in error.details["suggestion"]


def test_datasource_refresh_catalog_and_query_create_artifacts(services):
    install_fake_connector(services)
    datasource_id = create_mysql_datasource(services)

    test_result = services.datasource_service.test_datasource(datasource_id)
    assert test_result.ok is True

    catalog = services.datasource_service.refresh_catalog(datasource_id)
    assert [column.column_name for column in catalog] == ["id", "amount"]
    assert [column.column_name for column in services.datasource_service.get_catalog(datasource_id, "orders")] == ["id", "amount"]
    summary = services.datasource_service.get_catalog_summary(datasource_id)
    assert summary.table_count == 1
    assert summary.total_column_count == 2
    assert summary.tables[0].table_name == "orders"
    assert [column.name for column in summary.tables[0].columns] == ["id", "amount"]
    assert summary.usage_notes

    result = services.datasource_service.query_datasource(
        datasource_id,
        "select id, amount from orders",
        run_id="run1",
        row_limit=1,
        context=PolicyContext(run_id="run1"),
    )
    assert result.row_count == 1
    assert result.artifact_ref.type.value == "sql_result"
    record = services.artifact_registry.get_artifact(result.artifact_ref.artifact_id)
    assert record.preview["columns"] == ["id", "amount"]
    lineage = services.artifact_registry.get_lineage(result.artifact_ref.artifact_id)
    assert lineage[0]["edge_type"] == "query_result_of"
    assert services.artifact_registry.get_artifact(lineage[0]["parent_id"]).type.value == "sql_query"


def test_datasource_query_uses_connector_specific_validation(services):
    services.datasource_service.connectors = {DatasourceKind.mysql: ConnectorValidationBlocksQuery()}
    datasource_id = create_mysql_datasource(services)

    result = datasource_query_impl(
        datasource_id=datasource_id,
        query="select id from orders",
        run_id="run_connector_validation",
        services=services,
    )

    assert result.ok is False
    assert result.error.code == "POLICY_BLOCKED"
    assert result.error.message == "Connector-specific validation blocked the query."
    assert result.error.details["reason_type"] == "connector_validation"
    assert result.error.details["suggestion"] == "Use a query accepted by this datasource connector."
    assert services.artifact_registry.list_artifacts(run_id="run_connector_validation") == []


def test_datasource_mcp_tools_return_tool_result_envelope_and_block_unsafe_query(services):
    install_fake_connector(services)
    created = datasource_create_impl(
        name="local mysql",
        host="127.0.0.1",
        database="analytics",
        username="reader",
        password="secret",
        services=services,
    )
    assert created.ok is True
    assert "password" not in created.data
    datasource_id = created.data["datasource_id"]

    listed = datasource_list_impl(services=services)
    assert listed.ok is True
    assert listed.data[0]["datasource_id"] == datasource_id

    services.datasource_service.refresh_catalog(datasource_id)
    summary = datasource_get_catalog_summary_impl(datasource_id=datasource_id, services=services)
    assert summary.ok is True
    assert summary.data["table_count"] == 1
    assert summary.data["tables"][0]["columns"][0]["name"] == "id"

    blocked = datasource_query_impl(datasource_id=datasource_id, query="delete from orders", run_id="run1", services=services)
    assert blocked.ok is False
    assert blocked.error.code == "POLICY_BLOCKED"
    assert blocked.error.details["suggestion"] == "Rewrite the query as a single read-only SELECT."


def test_datasource_query_result_size_limit_keeps_only_query_artifact(services):
    services.datasource_service.connectors = {DatasourceKind.mysql: LargeResultConnector()}
    services.config.datasource_max_result_bytes = 50
    datasource_id = create_mysql_datasource(services)

    result = datasource_query_impl(datasource_id=datasource_id, query="select payload from large_table", run_id="run_large", services=services)

    assert result.ok is False
    assert result.error.code == "RESULT_TOO_LARGE"
    assert result.error.details["retryable"] is True
    assert result.error.details["query_artifact_id"].startswith("art_")
    query_artifacts = services.artifact_registry.list_artifacts(run_id="run_large", type=ArtifactType.sql_query)
    result_artifacts = services.artifact_registry.list_artifacts(run_id="run_large", type=ArtifactType.sql_result)
    assert [artifact.artifact_id for artifact in query_artifacts] == [result.error.details["query_artifact_id"]]
    assert result_artifacts == []


def test_datasource_query_errors_include_agent_recovery_details(services):
    services.datasource_service.connectors = {DatasourceKind.mysql: TimeoutConnector()}
    datasource_id = create_mysql_datasource(services)
    timeout = datasource_query_impl(datasource_id=datasource_id, query="select * from slow_table", run_id="run_timeout", services=services)
    assert timeout.ok is False
    assert timeout.error.code == "DATASOURCE_QUERY_TIMEOUT"
    assert timeout.error.details["datasource_id"] == datasource_id
    assert timeout.error.details["query_artifact_id"].startswith("art_")
    assert timeout.error.details["suggestion"] == "Add filters, aggregate earlier, or lower row_limit."

    services.datasource_service.connectors = {DatasourceKind.mysql: QueryErrorConnector()}
    failed = datasource_query_impl(datasource_id=datasource_id, query="select missing_column from orders", run_id="run_error", services=services)
    assert failed.ok is False
    assert failed.error.code == "DATASOURCE_QUERY_ERROR"
    assert failed.error.details["db_error_code"] == 1054
    assert failed.error.details["retryable"] is False
    assert failed.error.details["query_artifact_id"].startswith("art_")


def test_datasource_http_routes_use_tool_result_envelope(services):
    install_fake_connector(services)
    client = TestClient(create_app(services))
    created = client.post(
        "/datasources",
        json={
            "name": "local mysql",
            "host": "127.0.0.1",
            "database": "analytics",
            "username": "reader",
            "password": "secret",
        },
    ).json()
    assert created["ok"] is True
    datasource_id = created["data"]["datasource_id"]

    listed = client.get("/datasources").json()
    assert listed["ok"] is True
    assert listed["data"][0]["datasource_id"] == datasource_id

    client.post(f"/datasources/{datasource_id}/refresh-catalog", json={}).json()
    summary = client.get(f"/datasources/{datasource_id}/catalog-summary").json()
    assert summary["ok"] is True
    assert summary["data"]["tables"][0]["table_name"] == "orders"

    queried = client.post(
        f"/datasources/{datasource_id}/query",
        json={"query": "select id, amount from orders", "run_id": "run1", "row_limit": 1},
    ).json()
    assert queried["ok"] is True
    assert queried["data"]["row_count"] == 1


@pytest.mark.skipif(not os.environ.get("DATA_AGENT_TEST_MYSQL_URL"), reason="DATA_AGENT_TEST_MYSQL_URL is not set")
def test_real_mysql_datasource_integration_flow(services):
    url = make_url(os.environ["DATA_AGENT_TEST_MYSQL_URL"])
    assert url.database, "DATA_AGENT_TEST_MYSQL_URL must include a database name"
    assert url.password is not None, "DATA_AGENT_TEST_MYSQL_URL must include a password"

    created = services.datasource_service.create_datasource(
        DatasourceCreateRequest(
            name="integration mysql",
            host=url.host or "127.0.0.1",
            port=url.port or 3306,
            database=url.database,
            username=url.username or "",
            password=url.password,
        ),
        PolicyContext(user_id="integration"),
    )

    tested = services.datasource_service.test_datasource(created.datasource_id)
    assert tested.ok is True

    catalog = services.datasource_service.refresh_catalog(created.datasource_id)
    assert isinstance(catalog, list)

    queried = services.datasource_service.query_datasource(
        created.datasource_id,
        "select 1 as x",
        run_id="run_mysql_integration",
        row_limit=1,
        context=PolicyContext(run_id="run_mysql_integration"),
    )
    assert queried.row_count == 1
    assert queried.columns == ["x"]
    assert queried.sample_rows == [{"x": 1}]
