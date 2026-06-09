from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from data_agent_backend.api.app import create_app
from data_agent_backend.config import BackendConfig
from data_agent_backend.models.common import BackendError
from data_agent_backend.models.datasource import DatasourceCreateRequest, DatasourceType
from data_agent_backend.services.factory import create_backend_services


def _create_services(tmp_path):
    return create_backend_services(BackendConfig(base_data_dir=tmp_path / ".data_agent"))


def _register_datasource(services) -> str:
    record = services.datasource_service.register(
        DatasourceCreateRequest(
            name="analytics_mysql",
            type=DatasourceType.mysql,
            host="localhost",
            port=3306,
            database="analytics",
            username="analyst",
            password="secret",
        )
    )
    return record.datasource_id


def test_run_sql_query_requires_datasource_id(tmp_path) -> None:
    services = _create_services(tmp_path)
    run = services.run_service.create_run()

    with pytest.raises(BackendError) as exc_info:
        services.sql_executor.run_sql_query("SELECT 1 AS value", run.run_id)

    assert exc_info.value.code == "DATASOURCE_ID_REQUIRED"


def test_run_sql_query_uses_datasource_service_and_records_metadata(tmp_path, monkeypatch) -> None:
    services = _create_services(tmp_path)
    datasource_id = _register_datasource(services)
    run = services.run_service.create_run()
    calls = []

    def fake_query_datasource(received_datasource_id: str, query: str, row_limit: int):
        calls.append((received_datasource_id, query, row_limit))
        return [(42,)], ["answer"], "answer\r\n42\r\n"

    monkeypatch.setattr(services.datasource_service, "query_datasource", fake_query_datasource)

    ref = services.sql_executor.run_sql_query(
        "SELECT 42 AS answer",
        run.run_id,
        datasource_id=datasource_id,
        row_limit=25,
    )

    assert calls == [(datasource_id, "SELECT 42 AS answer", 25)]
    assert not hasattr(services.sql_executor, "_execute_duckdb")
    assert not hasattr(services.sql_executor, "_execute_sqlite")

    artifact = services.artifact_registry.get_artifact(ref.artifact_id)
    assert artifact.metadata["datasource_id"] == datasource_id
    assert artifact.metadata["row_limit"] == 25
    assert artifact.metadata["returned_rows"] == 1
    assert artifact.preview["columns"] == ["answer"]


def test_execution_sql_api_rejects_missing_datasource_id(tmp_path) -> None:
    services = _create_services(tmp_path)
    run = services.run_service.create_run()
    client = TestClient(create_app(services))

    response = client.post("/execution/sql", json={"query": "SELECT 1 AS value", "run_id": run.run_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "DATASOURCE_ID_REQUIRED"


def test_execution_sql_api_rejects_connection_id_field(tmp_path) -> None:
    services = _create_services(tmp_path)
    run = services.run_service.create_run()
    client = TestClient(create_app(services))

    response = client.post(
        "/execution/sql",
        json={"query": "SELECT 1 AS value", "run_id": run.run_id, "connection_id": "ds_legacy"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"
