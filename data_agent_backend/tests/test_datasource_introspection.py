from __future__ import annotations

import pytest

from data_agent_backend.config import BackendConfig
from data_agent_backend.models.common import BackendError
from data_agent_backend.models.datasource import DatasourceCreateRequest, DatasourceType
from data_agent_backend.services.factory import create_backend_services


MYSQL_ENV_KEYS = (
    "MYSQL_HOST",
    "MYSQL_DATABASE",
    "MYSQL_USERNAME",
    "MYSQL_PASSWORD",
    "MYSQL_PORT",
    "MYSQL_DATASOURCE_NAME",
)


def _services(tmp_path, monkeypatch):
    for key in MYSQL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return create_backend_services(BackendConfig(base_data_dir=tmp_path / ".data_agent"))


def _register(services, name: str = "analytics_mysql") -> str:
    record = services.datasource_service.register(
        DatasourceCreateRequest(
            name=name,
            type=DatasourceType.mysql,
            host="localhost",
            port=3306,
            database="analytics",
            username="analyst",
            password="secret",
        )
    )
    return record.datasource_id


def test_services_ignore_ambient_mysql_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MYSQL_HOST", "ambient-host")
    monkeypatch.setenv("MYSQL_DATABASE", "ambient_database")
    monkeypatch.setenv("MYSQL_USERNAME", "ambient_user")
    monkeypatch.setenv("MYSQL_PASSWORD", "ambient_secret")
    monkeypatch.setenv("MYSQL_PORT", "3307")
    monkeypatch.setenv("MYSQL_DATASOURCE_NAME", "ambient_mysql")

    services = _services(tmp_path, monkeypatch)

    assert services.datasource_service.list_all() == []


def test_resolve_datasource_id_requires_registered_datasource(tmp_path, monkeypatch) -> None:
    services = _services(tmp_path, monkeypatch)

    with pytest.raises(BackendError) as exc_info:
        services.datasource_service.resolve_datasource_id(None)

    assert exc_info.value.code == "DATASOURCE_REQUIRED"


def test_resolve_datasource_id_uses_single_registered_datasource(tmp_path, monkeypatch) -> None:
    services = _services(tmp_path, monkeypatch)
    datasource_id = _register(services)

    assert services.datasource_service.resolve_datasource_id(None) == datasource_id
    assert services.datasource_service.resolve_datasource_id(datasource_id) == datasource_id


def test_resolve_datasource_id_rejects_explicit_empty_string(tmp_path, monkeypatch) -> None:
    services = _services(tmp_path, monkeypatch)
    datasource_id = _register(services)

    with pytest.raises(BackendError) as exc_info:
        services.datasource_service.resolve_datasource_id("")

    assert exc_info.value.code == "NOT_FOUND"
    assert services.datasource_service.resolve_datasource_id(None) == datasource_id


def test_resolve_datasource_id_rejects_ambiguous_default(tmp_path, monkeypatch) -> None:
    services = _services(tmp_path, monkeypatch)
    _register(services, "primary")
    services.datasource_service.register(
        DatasourceCreateRequest(
            name="secondary",
            type=DatasourceType.mysql,
            host="localhost",
            port=3307,
            database="analytics_2",
            username="analyst",
            password="secret",
        )
    )

    with pytest.raises(BackendError) as exc_info:
        services.datasource_service.resolve_datasource_id(None)

    assert exc_info.value.code == "AMBIGUOUS_DATASOURCE"


def test_list_agent_datasources_hides_connection_secrets(tmp_path, monkeypatch) -> None:
    services = _services(tmp_path, monkeypatch)
    datasource_id = _register(services)

    data = services.datasource_service.list_agent_datasources()
    serialized_data = [item.model_dump(mode="json") for item in data]

    assert serialized_data == [
        {
            "datasource_id": datasource_id,
            "name": "analytics_mysql",
            "type": "mysql",
            "database": "analytics",
            "is_default": True,
        }
    ]
    serialized = str(data)
    assert "secret" not in serialized
    assert "analyst" not in serialized
    assert "localhost" not in serialized
