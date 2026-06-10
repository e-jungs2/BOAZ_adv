from __future__ import annotations

from data_agent_backend.config import BackendConfig
from data_agent_backend.mcp.tools_db import (
    db_describe_table,
    db_get_schema,
    db_list_datasources,
    db_run_analysis_query,
    db_sample_rows,
)
from data_agent_backend.models.datasource import DatasourceCreateRequest, DatasourceType
from data_agent_backend.services.factory import create_backend_services


def _services(tmp_path):
    return create_backend_services(BackendConfig(base_data_dir=tmp_path / ".data_agent"))


def _register(services) -> str:
    return services.datasource_service.register(
        DatasourceCreateRequest(
            name="analytics_mysql",
            type=DatasourceType.mysql,
            host="localhost",
            port=3306,
            database="analytics",
            username="analyst",
            password="secret",
        )
    ).datasource_id


def test_db_list_datasources_returns_tool_result(tmp_path) -> None:
    services = _services(tmp_path)
    datasource_id = _register(services)

    result = db_list_datasources(services=services)

    assert result.ok is True
    assert result.data[0]["datasource_id"] == datasource_id
    assert "username" not in result.data[0]
    assert "host" not in result.data[0]


def test_db_run_analysis_query_creates_run_when_context_has_no_run_id(tmp_path, monkeypatch) -> None:
    services = _services(tmp_path)
    datasource_id = _register(services)
    expected_datasource_id = datasource_id

    def fake_run_analysis_query(query, run_id, datasource_id=None, context=None, row_limit=None):
        assert query == "SELECT 1 AS value"
        assert run_id.startswith("run_")
        assert datasource_id == expected_datasource_id
        return {
            "artifact_ref": {"artifact_id": "art_1", "type": "sql_result", "format": "csv"},
            "preview": {"columns": ["value"], "rows": [{"value": 1}], "truncated": False},
            "profile": {"returned_rows": 1, "preview_rows": 1, "column_count": 1},
            "execution": {
                "datasource_id": datasource_id,
                "tool_name": "db_run_analysis_query",
                "row_limit": row_limit or 1000,
                "runtime_ms": 1,
            },
            "warnings": [],
        }

    monkeypatch.setattr(services.sql_executor, "run_analysis_query", fake_run_analysis_query)

    result = db_run_analysis_query("SELECT 1 AS value", datasource_id=datasource_id, services=services)

    assert result.ok is True
    assert result.data["artifact_ref"]["artifact_id"] == "art_1"


def test_db_tools_wrap_failures(tmp_path) -> None:
    services = _services(tmp_path)

    result = db_get_schema(services=services)

    assert result.ok is False
    assert result.error.code == "DATASOURCE_REQUIRED"


def test_db_tool_functions_are_callable() -> None:
    assert callable(db_describe_table)
    assert callable(db_get_schema)
    assert callable(db_list_datasources)
    assert callable(db_run_analysis_query)
    assert callable(db_sample_rows)
