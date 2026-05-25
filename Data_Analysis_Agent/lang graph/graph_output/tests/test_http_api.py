from __future__ import annotations

from fastapi.testclient import TestClient

from data_agent_backend.api import create_app
from data_agent_backend.models.contexts import PolicyContext
from data_agent_backend.models.execution import ExecutionResult, ExecutionStatus


def client_for(services):
    return TestClient(create_app(services))


def test_health_returns_tool_result(services):
    response = client_for(services).get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": {"status": "ok"}, "error": None}


def test_agent_ask_endpoint_returns_tool_result(monkeypatch, services):
    from data_agent_agent.runtime import AgentRunResult

    class FakeRuntime:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def run(self, request):
            assert request.question == "월별 주문 수"
            assert request.datasource_id == "ds_1"
            assert request.model == "gpt-test"
            assert request.row_limit == 50
            assert request.python_timeout_ms == 450000
            assert request.metadata == {"ui": "prototype"}
            assert request.source == "data-agent-api"
            return AgentRunResult(answer="월별 주문 수 답변", run_id="run_1", datasource_id="ds_1", raw_result={})

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("data_agent_backend.api.routes_agent.AgentRuntime", FakeRuntime)

    response = client_for(services).post(
        "/agent/ask",
        json={
            "question": "월별 주문 수",
            "datasource_id": "ds_1",
            "model": "gpt-test",
            "row_limit": 50,
            "python_timeout_ms": 450000,
            "metadata": {"ui": "prototype"},
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body == {
        "ok": True,
        "data": {
            "answer": "월별 주문 수 답변",
            "run_id": "run_1",
            "datasource_id": "ds_1",
        },
        "error": None,
    }


def test_agent_ask_endpoint_returns_error_envelope(monkeypatch, services):
    from data_agent_agent.config import AgentConfig
    from data_agent_agent.runtime import AgentRuntimeError

    class FakeRuntime:
        def __init__(self, **_kwargs):
            pass

        async def run(self, _request):
            raise AgentRuntimeError("agent failed")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "data_agent_backend.api.routes_agent.AgentConfig.from_env",
        lambda **_kwargs: AgentConfig(openai_api_key="test-key"),
    )
    monkeypatch.setattr("data_agent_backend.api.routes_agent.AgentRuntime", FakeRuntime)

    response = client_for(services).post("/agent/ask", json={"question": "question"})
    assert response.status_code == 200
    body = response.json()

    assert body["ok"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "AGENT_RUNTIME_ERROR"
    assert body["error"]["message"] == "agent failed"


def test_agent_ask_endpoint_preserves_runtime_error_details(monkeypatch, services):
    from data_agent_agent.config import AgentConfig
    from data_agent_agent.runtime import AgentRuntimeError

    class FakeRuntime:
        def __init__(self, **_kwargs):
            pass

        async def run(self, _request):
            raise AgentRuntimeError(
                "datasource_test 실패: DATASOURCE_CONNECTION_ERROR - Datasource connection failed.",
                details={
                    "bootstrap_step": "datasource_test",
                    "backend_code": "DATASOURCE_CONNECTION_ERROR",
                    "backend_message": "Datasource connection failed.",
                    "suggestion": "Check credentials.",
                    "retryable": True,
                },
            )

    monkeypatch.setattr(
        "data_agent_backend.api.routes_agent.AgentConfig.from_env",
        lambda **_kwargs: AgentConfig(openai_api_key="test-key"),
    )
    monkeypatch.setattr("data_agent_backend.api.routes_agent.AgentRuntime", FakeRuntime)

    response = client_for(services).post("/agent/ask", json={"question": "question"})
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "AGENT_RUNTIME_ERROR"
    assert body["error"]["details"] == {
        "bootstrap_step": "datasource_test",
        "backend_code": "DATASOURCE_CONNECTION_ERROR",
        "backend_message": "Datasource connection failed.",
        "suggestion": "Check credentials.",
        "retryable": True,
    }


def test_agent_ask_endpoint_preserves_config_error_details(monkeypatch, services):
    from data_agent_agent.config import AgentConfigError

    def raise_missing_mysql(**_kwargs):
        raise AgentConfigError(
            ".env의 MySQL datasource 설정이 부족합니다.",
            details={"missing_env_vars": ["DATA_AGENT_MYSQL_HOST", "DATA_AGENT_MYSQL_PASSWORD"]},
        )

    monkeypatch.setattr("data_agent_backend.api.routes_agent.AgentConfig.from_env", raise_missing_mysql)

    response = client_for(services).post("/agent/ask", json={"question": "question"})
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "AGENT_CONFIG_ERROR"
    assert body["error"]["details"] == {
        "missing_env_vars": ["DATA_AGENT_MYSQL_HOST", "DATA_AGENT_MYSQL_PASSWORD"]
    }


def test_agent_ask_with_explicit_datasource_does_not_parse_mysql_env(monkeypatch, services):
    from data_agent_agent.runtime import AgentRunResult

    from_env_calls = []

    def fake_from_env(**_kwargs):
        from_env_calls.append(_kwargs)
        raise AssertionError("from_env should not run for explicit datasource")

    class FakeRuntime:
        def __init__(self, **kwargs):
            assert kwargs["config"] is None

        async def run(self, request):
            assert request.datasource_id == "ds_1"
            return AgentRunResult(answer="ok", run_id="run_1", datasource_id="ds_1", raw_result={})

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DATA_AGENT_MYSQL_PORT", "not-int")
    monkeypatch.setattr("data_agent_backend.api.routes_agent.AgentConfig.from_env", fake_from_env)
    monkeypatch.setattr("data_agent_backend.api.routes_agent.AgentRuntime", FakeRuntime)

    response = client_for(services).post("/agent/ask", json={"question": "question", "datasource_id": "ds_1"})
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["data"]["datasource_id"] == "ds_1"
    assert from_env_calls == []


def test_agent_ask_endpoint_maps_unexpected_agent_error(monkeypatch, services):
    from data_agent_agent.config import AgentConfig

    class FakeRuntime:
        def __init__(self, **_kwargs):
            pass

        async def run(self, _request):
            raise ValueError("boom")

    monkeypatch.setattr(
        "data_agent_backend.api.routes_agent.AgentConfig.from_env",
        lambda **_kwargs: AgentConfig(openai_api_key="test-key"),
    )
    monkeypatch.setattr("data_agent_backend.api.routes_agent.AgentRuntime", FakeRuntime)

    response = client_for(services).post("/agent/ask", json={"question": "question", "datasource_id": "ds_1"})
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "AGENT_RUNTIME_ERROR"
    assert body["error"]["message"] == "Agent runtime failed unexpectedly."
    assert body["error"]["details"] == {"type": "ValueError"}


def test_agent_ask_endpoint_rejects_bool_python_timeout(services):
    response = client_for(services).post(
        "/agent/ask",
        json={"question": "question", "datasource_id": "ds_1", "python_timeout_ms": True},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_agent_ask_endpoint_rejects_zero_python_timeout(services):
    response = client_for(services).post(
        "/agent/ask",
        json={"question": "question", "datasource_id": "ds_1", "python_timeout_ms": 0},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "AGENT_CONFIG_ERROR"
    assert "python_timeout_ms" in body["error"]["message"]


def test_agent_ask_endpoint_rejects_python_timeout_above_max(services):
    response = client_for(services).post(
        "/agent/ask",
        json={"question": "question", "datasource_id": "ds_1", "python_timeout_ms": 600001},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "AGENT_CONFIG_ERROR"
    assert "python_timeout_ms" in body["error"]["message"]


def test_agent_ask_endpoint_reports_missing_openai_key(monkeypatch, services):
    from data_agent_agent.config import AgentConfigError

    def raise_missing_key(**_kwargs):
        raise AgentConfigError("OPENAI_API_KEY is required")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("data_agent_backend.api.routes_agent.AgentConfig.from_env", raise_missing_key)

    response = client_for(services).post("/agent/ask", json={"question": "question"})
    assert response.status_code == 200
    body = response.json()

    assert body["ok"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "AGENT_CONFIG_ERROR"
    assert "OPENAI_API_KEY" in body["error"]["message"]


def test_workspace_write_text_and_policy_block(services):
    client = client_for(services)
    ok = client.post(
        "/workspace/write-text",
        json={
            "path": "/workspace/a.txt",
            "content": "hello",
            "context": {"run_id": "run1", "thread_id": "thread1", "project_id": "project1", "user_id": "user1"},
        },
    ).json()
    assert ok["ok"] is True

    blocked = client.post("/workspace/write-text", json={"path": "/artifacts/a.txt", "content": "hello"}).json()
    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "POLICY_BLOCKED"


def test_execution_sql_endpoint_creates_artifact_and_blocks_unsafe_sql(services):
    client = client_for(services)
    ok = client.post("/execution/sql", json={"query": "select 1 as x union all select 2 as x", "run_id": "run1", "row_limit": 1}).json()
    assert ok["ok"] is True
    assert ok["data"]["type"] == "sql_result"
    assert ok["data"]["preview"]["row_count"] == 1

    for query in ["delete from t", "select 1; select 2"]:
        blocked = client.post("/execution/sql", json={"query": query, "run_id": "run1"}).json()
        assert blocked["ok"] is False
        assert blocked["error"]["code"] == "POLICY_BLOCKED"


def test_execution_python_endpoint_keeps_disabled_contract(services):
    result = client_for(services).post("/execution/python", json={"code": "print('nope')", "run_id": "run1"}).json()
    assert result["ok"] is True
    assert result["data"]["status"] == "approval_required"


def test_execution_python_endpoint_rejects_invalid_timeout_before_approval(services):
    result = client_for(services).post(
        "/execution/python",
        json={"code": "print('nope')", "run_id": "run1", "timeout_ms": 0},
    ).json()

    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_execution_python_endpoint_rejects_bool_timeout(services):
    result = client_for(services).post(
        "/execution/python",
        json={"code": "print('nope')", "run_id": "run1", "timeout_ms": True},
    ).json()

    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_execution_python_endpoint_passes_timeout_to_executor_limits(services):
    captured_limits = []

    class CapturingSandboxExecutor:
        def run_python(self, code, inputs, limits, context):
            captured_limits.append(limits)
            return ExecutionResult(execution_id="exec_1", status=ExecutionStatus.success)

    services.sandbox_executor = CapturingSandboxExecutor()

    result = client_for(services).post(
        "/execution/python",
        json={"code": "print('ok')", "run_id": "run1", "timeout_ms": 1234},
    ).json()

    assert result["ok"] is True
    assert captured_limits[0].timeout_ms == 1234


def test_execution_python_endpoint_runs_local_backend(tmp_path):
    from data_agent_backend.config import BackendConfig
    from data_agent_backend.services import create_backend_services

    local_services = create_backend_services(BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local"))
    result = client_for(local_services).post(
        "/execution/python",
        json={
            "code": "import os; from pathlib import Path; Path(os.environ['DATA_AGENT_OUTPUTS_DIR']).joinpath('api.txt').write_text('ok', encoding='utf-8'); print('api-ok')",
            "run_id": "run1",
        },
    ).json()

    assert result["ok"] is True
    assert result["data"]["status"] == "success"
    assert result["data"]["exit_code"] == 0
    assert "api-ok" in result["data"]["stdout"]
    assert len(result["data"]["created_artifact_ids"]) >= 2


def test_memory_propose_and_approval_flow(services):
    client = client_for(services)
    proposed = client.post(
        "/memory/propose",
        json={
            "namespace": ["user", "u1", "project", "p1"],
            "type": "business_glossary",
            "content": "email,name\nalice@example.com,Alice",
            "source": {"artifact_id": "a1"},
            "context": {"user_id": "u1", "project_id": "p1"},
        },
    ).json()
    assert proposed["ok"] is True
    assert proposed["data"]["status"] == "pending"

    pending = client.post("/approvals/pending", json={}).json()
    assert pending["ok"] is True
    assert len(pending["data"]) == 1
    approval_id = pending["data"][0]["approval_id"]

    resolved = client.post(
        "/approvals/resolve",
        json={"approval_id": approval_id, "decision": "approve", "context": {"user_id": "reviewer"}},
    ).json()
    assert resolved["ok"] is True
    assert resolved["data"]["status"] == "approved"


def test_validation_errors_use_tool_result_envelope(services):
    response = client_for(services).post("/workspace/write-text", json={"path": "/workspace/a.txt"})
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_run_http_create_get_list_and_status_terminal_block(services):
    client = client_for(services)
    created = client.post(
        "/runs/create",
        json={"run_id": "run1", "thread_id": "thread1", "project_id": "project1", "metadata": {"goal": "profile"}},
    ).json()
    assert created["ok"] is True
    assert created["data"]["status"] == "created"

    got = client.post("/runs/get", json={"run_id": "run1"}).json()
    assert got["data"]["metadata"] == {"goal": "profile"}

    listed = client.post("/runs/list", json={"thread_id": "thread1", "project_id": "project1", "status": "created"}).json()
    assert [item["run_id"] for item in listed["data"]] == ["run1"]

    updated = client.post("/runs/update-status", json={"run_id": "run1", "status": "succeeded"}).json()
    assert updated["ok"] is True
    assert updated["data"]["status"] == "succeeded"

    blocked = client.post("/runs/update-status", json={"run_id": "run1", "status": "failed"}).json()
    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "RUN_TERMINAL"


def test_run_http_events_and_summary_include_artifacts_and_pending_approvals(services):
    client = client_for(services)
    client.post("/runs/create", json={"run_id": "run1"}).json()
    artifact = client.post(
        "/artifacts/register",
        json={"payload": {"run_id": "run1", "type": "report", "content_text": "hello", "created_by_tool": "test"}},
    ).json()["data"]
    approval = services.approval_store.create_approval_request(
        "export.create",
        "/exports",
        {"format": "csv"},
        PolicyContext(run_id="run1"),
    )

    appended = client.post(
        "/runs/events/append",
        json={"run_id": "run1", "event_type": "artifact_created", "message": "registered", "artifact_ids": [artifact["artifact_id"]]},
    ).json()
    assert appended["ok"] is True

    events = client.post("/runs/events/list", json={"run_id": "run1"}).json()
    assert [event["event_type"] for event in events["data"]] == ["artifact_created"]

    summary = client.post("/runs/summary", json={"run_id": "run1"}).json()
    assert summary["ok"] is True
    assert [item["artifact_id"] for item in summary["data"]["artifacts"]] == [artifact["artifact_id"]]
    assert [item["approval_id"] for item in summary["data"]["pending_approvals"]] == [approval.approval_id]


def test_run_http_invalid_status_uses_tool_result_envelope(services):
    client = client_for(services)
    client.post("/runs/create", json={"run_id": "run1"})
    body = client.post("/runs/update-status", json={"run_id": "run1", "status": "not-a-status"}).json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
