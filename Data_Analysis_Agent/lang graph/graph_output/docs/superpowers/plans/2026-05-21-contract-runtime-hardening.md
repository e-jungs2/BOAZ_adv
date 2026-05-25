# Contract Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MCP/API `ToolResult` 계약을 고정하고, 그 위에서 CLI/Agent runtime을 Agent adapter 기반으로 안정화한다.

**Architecture:** 먼저 backend contract 테스트를 보강해 외부 응답 shape과 MCP wrapper 규칙을 고정한다. 그 다음 `data_agent_agent`에 작은 Agent runner adapter 경계를 도입하고, datasource bootstrap 단계와 runtime 오류 details를 명확히 만든다.

**Tech Stack:** Python 3.11, pytest, FastAPI TestClient, Pydantic v2, MCP FastMCP, LangChain tool, DeepAgents adapter

---

## 파일 구조

- Modify: `src/data_agent_backend/models/tool_results.py`
  - `ToolResult` 실패/예외 변환 계약을 유지한다.
- Modify: `src/data_agent_backend/mcp/server.py`
  - MCP public schema에서 `services` 인자가 숨겨지는 wrapper 계약을 유지한다.
- Modify: `src/data_agent_backend/mcp/tools_*.py`
  - public 함수와 `_impl(..., services)` 패턴이 깨진 도구가 있으면 정리한다.
- Modify: `src/data_agent_backend/api/routes_agent.py`
  - `AgentConfigError`와 `AgentRuntimeError` details를 `ToolResult`에 보존한다.
- Modify: `src/data_agent_agent/config.py`
  - config/env 오류에 기계가 읽을 수 있는 details를 추가한다.
- Modify: `src/data_agent_agent/runtime.py`
  - `AgentRunner` adapter 경계, bootstrap 단계명, trace/run metadata, runtime error details를 추가한다.
- Modify: `src/data_agent_agent/tools.py`
  - raw tool 결과 정규화 테스트를 만족하도록 `normalize_tool_result()`를 유지 또는 보강한다.
- Modify: `src/data_agent_agent/runner.py`
  - CLI 오류 출력에 runtime details 중 핵심 정보를 반영한다.
- Test: `tests/test_mcp_server.py`
  - MCP public schema와 wrapper 계약을 보강한다.
- Test: `tests/test_http_api.py`
  - HTTP error envelope와 `/agent/ask` details 보존을 보강한다.
- Test: `tests/test_agent_layer.py`
  - Agent adapter, bootstrap 단계, trace/run metadata, normalize contract를 보강한다.
- Test: `tests/test_tool_results.py`
  - `ToolResult` 자체 계약을 분리해서 검증한다.

## Task 1: ToolResult 계약 테스트 분리

**Files:**
- Create: `tests/test_tool_results.py`
- Modify: `src/data_agent_backend/models/tool_results.py`

- [ ] **Step 1: 실패하는 ToolResult 계약 테스트 추가**

Create `tests/test_tool_results.py`:

```python
from __future__ import annotations

from data_agent_backend.models.common import BackendError
from data_agent_backend.models.tool_results import ToolResult


def test_tool_result_success_shape_is_stable():
    result = ToolResult.success({"status": "ok"}).model_dump(mode="json")

    assert result == {"ok": True, "data": {"status": "ok"}, "error": None}


def test_tool_result_failure_shape_is_stable():
    result = ToolResult.failure(
        "EXAMPLE_ERROR",
        "Example failed.",
        {"suggestion": "Retry with a smaller request.", "retryable": True},
    ).model_dump(mode="json")

    assert result == {
        "ok": False,
        "data": None,
        "error": {
            "code": "EXAMPLE_ERROR",
            "message": "Example failed.",
            "details": {"suggestion": "Retry with a smaller request.", "retryable": True},
        },
    }


def test_tool_result_from_backend_error_preserves_details():
    exc = BackendError(
        "DATASOURCE_QUERY_ERROR",
        "Datasource query failed.",
        {"suggestion": "Inspect catalog.", "retryable": False, "query_artifact_id": "art_query"},
    )

    result = ToolResult.from_exception(exc).model_dump(mode="json")

    assert result["ok"] is False
    assert result["error"]["code"] == "DATASOURCE_QUERY_ERROR"
    assert result["error"]["message"] == "Datasource query failed."
    assert result["error"]["details"] == {
        "suggestion": "Inspect catalog.",
        "retryable": False,
        "query_artifact_id": "art_query",
    }


def test_tool_result_from_unknown_exception_masks_message():
    result = ToolResult.from_exception(ValueError("secret internal value")).model_dump(mode="json")

    assert result["ok"] is False
    assert result["data"] is None
    assert result["error"]["code"] == "INTERNAL_ERROR"
    assert result["error"]["message"] == "An internal backend error occurred."
    assert result["error"]["details"] == {"type": "ValueError"}
```

- [ ] **Step 2: 테스트 실패 또는 기존 통과 확인**

Run:

```powershell
uv run pytest tests/test_tool_results.py -q
```

Expected: 기존 구현이 이미 계약을 만족하면 PASS. 실패한다면 실패 지점은 `ToolResult.from_exception()`의 details 보존 또는 unknown exception masking이다.

- [ ] **Step 3: ToolResult 구현을 계약 코드와 대조**

Update `src/data_agent_backend/models/tool_results.py` only when the current methods differ from this contract code:

```python
    @classmethod
    def failure(cls, code: str, message: str, details: JsonDict | None = None) -> "ToolResult":
        return cls(ok=False, data=None, error=ToolError(code=code, message=message, details=details or {}))

    @classmethod
    def from_exception(cls, exc: Exception) -> "ToolResult":
        if isinstance(exc, BackendError):
            return cls.failure(exc.code, exc.message, exc.details)
        return cls.failure("INTERNAL_ERROR", "An internal backend error occurred.", {"type": type(exc).__name__})
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
uv run pytest tests/test_tool_results.py -q
```

Expected: PASS.

- [ ] **Step 5: 커밋**

```powershell
git add tests/test_tool_results.py src/data_agent_backend/models/tool_results.py
git commit -m "Harden ToolResult contract tests"
```

## Task 2: MCP public wrapper와 impl 패턴 고정

**Files:**
- Modify: `tests/test_mcp_server.py`
- Modify: `src/data_agent_backend/mcp/server.py`
- Modify: `src/data_agent_backend/mcp/tools_analysis_context.py`

- [ ] **Step 1: MCP public schema와 impl 패턴 테스트 추가**

Append to `tests/test_mcp_server.py`:

```python
from data_agent_backend.mcp import tools_analysis_context


def test_all_registered_mcp_tools_hide_services_after_public_wrapping():
    for fn in PUBLIC_TOOL_FUNCTIONS + [
        tools_analysis_context.analysis_catalog_search,
        tools_analysis_context.analysis_get_table_profile,
        tools_analysis_context.analysis_get_column_profile,
        tools_analysis_context.analysis_semantic_search,
        tools_analysis_context.analysis_get_join_paths,
        tools_analysis_context.analysis_build_context,
        tools_analysis_context.analysis_profile_datasource,
        tools_analysis_context.analysis_load_semantic_seed,
        tools_analysis_context.analysis_upsert_table_profile,
        tools_analysis_context.analysis_upsert_column_profile,
        tools_analysis_context.analysis_upsert_metric,
        tools_analysis_context.analysis_upsert_business_term,
        tools_analysis_context.analysis_upsert_mart,
        tools_analysis_context.analysis_upsert_join_path,
    ]:
        wrapped = _mcp_public_tool(fn)
        signature = inspect.signature(wrapped)
        assert "services" not in signature.parameters, fn.__name__
        assert "services" not in getattr(wrapped, "__annotations__", {}), fn.__name__


def test_analysis_context_tools_expose_impl_entrypoints():
    expected_impl_names = [
        "analysis_catalog_search_impl",
        "analysis_get_table_profile_impl",
        "analysis_get_column_profile_impl",
        "analysis_semantic_search_impl",
        "analysis_get_join_paths_impl",
        "analysis_build_context_impl",
        "analysis_profile_datasource_impl",
        "analysis_load_semantic_seed_impl",
        "analysis_upsert_table_profile_impl",
        "analysis_upsert_column_profile_impl",
        "analysis_upsert_metric_impl",
        "analysis_upsert_business_term_impl",
        "analysis_upsert_mart_impl",
        "analysis_upsert_join_path_impl",
    ]
    missing = [name for name in expected_impl_names if not hasattr(tools_analysis_context, name)]
    assert missing == []

    for name in expected_impl_names:
        signature = inspect.signature(getattr(tools_analysis_context, name))
        assert "services" in signature.parameters, name
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
uv run pytest tests/test_mcp_server.py -q
```

Expected: FAIL because `tools_analysis_context.py` currently uses optional `services` on public functions and does not expose `_impl` functions.

- [ ] **Step 3: `tools_analysis_context.py`에 public/impl 분리 적용**

For each existing function in `src/data_agent_backend/mcp/tools_analysis_context.py`, split the public function into a wrapper and an `_impl` function. The first two functions should look like this pattern:

```python
def analysis_catalog_search(
    datasource_id: str,
    query: str,
    limit: int = 10,
) -> ToolResult:
    return analysis_catalog_search_impl(
        datasource_id=datasource_id,
        query=query,
        limit=limit,
        services=get_services(),
    )


def analysis_catalog_search_impl(
    *,
    datasource_id: str,
    query: str,
    limit: int = 10,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.analysis_context_service.catalog_search(datasource_id, query, limit))


def analysis_get_table_profile(
    datasource_id: str,
    table_name: str,
    schema_name: str | None = None,
) -> ToolResult:
    return analysis_get_table_profile_impl(
        datasource_id=datasource_id,
        table_name=table_name,
        schema_name=schema_name,
        services=get_services(),
    )


def analysis_get_table_profile_impl(
    *,
    datasource_id: str,
    table_name: str,
    schema_name: str | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.analysis_context_service.get_table_profile(datasource_id, table_name, schema_name))
```

Apply the same shape to the remaining analysis context functions. Public functions must not include a `services` parameter. `_impl` functions must require `services: BackendServices`.

- [ ] **Step 4: Import path compatibility 확인**

Run:

```powershell
uv run pytest tests/test_analysis_context.py tests/test_mcp_server.py -q
```

Expected: PASS. If a test imports a public function and passes `services`, update that test to call the matching `_impl` function instead.

- [ ] **Step 5: 커밋**

```powershell
git add tests/test_mcp_server.py tests/test_analysis_context.py src/data_agent_backend/mcp/tools_analysis_context.py src/data_agent_backend/mcp/server.py
git commit -m "Harden MCP analysis tool wrappers"
```

## Task 3: HTTP `/agent/ask` 오류 details 보존

**Files:**
- Modify: `tests/test_http_api.py`
- Modify: `src/data_agent_backend/api/routes_agent.py`
- Modify: `src/data_agent_agent/config.py`
- Modify: `src/data_agent_agent/runtime.py`

- [ ] **Step 1: `/agent/ask` details 보존 테스트 추가**

Append to `tests/test_http_api.py`:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
uv run pytest tests/test_http_api.py::test_agent_ask_endpoint_preserves_runtime_error_details tests/test_http_api.py::test_agent_ask_endpoint_preserves_config_error_details -q
```

Expected: FAIL because `AgentConfigError` and `AgentRuntimeError` do not yet expose `details`, and `routes_agent.py` currently drops details.

- [ ] **Step 3: Agent error classes에 details 추가**

Update `src/data_agent_agent/config.py`:

```python
class AgentConfigError(RuntimeError):
    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}
```

Update `src/data_agent_agent/runtime.py`:

```python
class AgentRuntimeError(RuntimeError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}
```

- [ ] **Step 4: config 오류 details 생성**

In `src/data_agent_agent/config.py`, update `mysql_create_payload()`:

```python
    def mysql_create_payload(self) -> dict[str, object]:
        missing = self.missing_mysql_env_vars()
        if missing:
            raise AgentConfigError(
                ".env의 MySQL datasource 설정이 부족합니다. 누락된 환경 변수: " + ", ".join(missing),
                {"missing_env_vars": missing},
            )
        return {
            "kind": "mysql",
            "name": self.mysql_name,
            "host": self.mysql_host,
            "port": self.mysql_port,
            "database": self.mysql_database,
            "username": self.mysql_username,
            "password": self.mysql_password,
        }
```

- [ ] **Step 5: `/agent/ask`에서 details 보존**

Update exception handling in `src/data_agent_backend/api/routes_agent.py`:

```python
    except AgentConfigError as exc:
        return dump_result(ToolResult.failure("AGENT_CONFIG_ERROR", str(exc), getattr(exc, "details", {})))
    except AgentRuntimeError as exc:
        return dump_result(ToolResult.failure("AGENT_RUNTIME_ERROR", str(exc), getattr(exc, "details", {})))
    except Exception as exc:
        return dump_result(ToolResult.failure("AGENT_RUNTIME_ERROR", str(exc), {"type": type(exc).__name__}))
```

- [ ] **Step 6: 관련 테스트 통과 확인**

Run:

```powershell
uv run pytest tests/test_http_api.py tests/test_agent_layer.py::test_run_cli_without_datasource_id_requires_mysql_env -q
```

Expected: PASS.

- [ ] **Step 7: 커밋**

```powershell
git add tests/test_http_api.py tests/test_agent_layer.py src/data_agent_backend/api/routes_agent.py src/data_agent_agent/config.py src/data_agent_agent/runtime.py
git commit -m "Preserve agent error details in API responses"
```

## Task 4: AgentRunner adapter 경계 도입

**Files:**
- Modify: `tests/test_agent_layer.py`
- Modify: `src/data_agent_agent/runtime.py`

- [ ] **Step 1: adapter 경계 테스트 추가**

Append to `tests/test_agent_layer.py`:

```python
def test_agent_runtime_uses_agent_runner_adapter():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        class FakeRunner:
            async def run(self, *, question, model, tools, metadata):
                events.append(
                    (
                        "runner_run",
                        {
                            "question": question,
                            "model": model,
                            "tool_names": [tool.name for tool in tools],
                            "metadata": metadata,
                        },
                    )
                )
                return {"answer": "adapter answer", "raw_result": {"adapter": True}}

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key", openai_model="gpt-test"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_runner=FakeRunner(),
        )

        result = await runtime.run(AgentRunRequest(datasource_id="ds_1", question="질문"))

        assert result.answer == "adapter answer"
        assert result.raw_result == {"adapter": True}
        assert events[0][0] == "run_create"
        assert events[1][0] == "runner_run"
        assert events[1][1]["question"] == "질문"
        assert events[1][1]["model"] == "gpt-test"
        assert "run_sql" in events[1][1]["tool_names"]
        assert events[1][1]["metadata"]["run_id"] == "run_1"
        assert events[1][1]["metadata"]["datasource_id"] == "ds_1"

    asyncio.run(scenario())
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_agent_runtime_uses_agent_runner_adapter -q
```

Expected: FAIL because `AgentRuntime.__init__` does not accept `agent_runner`.

- [ ] **Step 3: runtime에 runner protocol과 DeepAgents adapter 추가**

In `src/data_agent_agent/runtime.py`, add these definitions near the dataclasses:

```python
class AgentRunner(Protocol):
    async def run(
        self,
        *,
        question: str,
        model: str,
        tools: list[Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class DeepAgentsRunner:
    def __init__(self, agent_factory: AgentFactory = create_data_agent) -> None:
        self.agent_factory = agent_factory

    async def run(
        self,
        *,
        question: str,
        model: str,
        tools: list[Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        agent = self.agent_factory(model=model, tools=tools)
        result = agent.ainvoke({"messages": [{"role": "user", "content": question}]})
        if inspect.isawaitable(result):
            result = await result
        return {"answer": extract_final_content(result), "raw_result": result}
```

Also add `Protocol` to the import line:

```python
from typing import Any, Callable, Protocol
```

- [ ] **Step 4: AgentRuntime 생성자와 run 경로 변경**

Update `AgentRuntime.__init__`:

```python
    def __init__(
        self,
        *,
        config: AgentConfig | None = None,
        tool_provider: BackendToolProvider | None = None,
        agent_factory: AgentFactory = create_data_agent,
        agent_runner: AgentRunner | None = None,
    ) -> None:
        self.config = config
        self.tool_provider = tool_provider or MCPBackendToolProvider()
        self.agent_runner = agent_runner or DeepAgentsRunner(agent_factory)
```

Replace the agent invocation section in `AgentRuntime.run()`:

```python
        agent_metadata = {
            "run_id": run_id,
            "datasource_id": resolved_datasource_id,
            "source": request.source,
            "model": config.openai_model,
            "trace_name": self._trace_name(request.source, resolved_datasource_id, run_id),
        }
        runner_result = await self.agent_runner.run(
            question=request.question,
            model=config.openai_model,
            tools=tools,
            metadata=agent_metadata,
        )
        return AgentRunResult(
            answer=str(runner_result.get("answer", "")),
            run_id=run_id,
            datasource_id=resolved_datasource_id,
            raw_result=runner_result.get("raw_result"),
        )
```

Add helper method:

```python
    def _trace_name(self, source: str, datasource_id: str, run_id: str) -> str:
        return f"data-agent:{source}:{datasource_id}:{run_id}"
```

- [ ] **Step 5: 기존 fake agent 테스트 호환성 확인**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_run_create_is_called_before_agent_invoke tests/test_agent_layer.py::test_agent_runtime_uses_agent_runner_adapter tests/test_agent_layer.py::test_agent_runtime_awaits_future_agent_result -q
```

Expected: PASS. Existing `agent_factory` based tests must still work through `DeepAgentsRunner`.

- [ ] **Step 6: 커밋**

```powershell
git add tests/test_agent_layer.py src/data_agent_agent/runtime.py
git commit -m "Add agent runner adapter boundary"
```

## Task 5: datasource bootstrap 단계별 runtime 오류 details

**Files:**
- Modify: `tests/test_agent_layer.py`
- Modify: `src/data_agent_agent/runtime.py`

- [ ] **Step 1: bootstrap 단계 details 테스트 추가**

Append to `tests/test_agent_layer.py`:

```python
def test_datasource_bootstrap_error_includes_step_and_backend_details():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(
            events,
            datasource_refresh_catalog=FakeRawTool(
                "datasource_refresh_catalog",
                {
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "DATASOURCE_CATALOG_ERROR",
                        "message": "refresh failed",
                        "details": {"suggestion": "Check grants.", "retryable": True},
                    },
                },
                events,
            ),
        )

        with pytest.raises(RuntimeAgentRuntimeError) as exc_info:
            await resolve_datasource_id(raw_tools, mysql_config(), None)

        exc = exc_info.value
        assert "datasource_refresh_catalog 실패" in str(exc)
        assert exc.details == {
            "bootstrap_step": "datasource_refresh_catalog",
            "backend_code": "DATASOURCE_CATALOG_ERROR",
            "backend_message": "refresh failed",
            "suggestion": "Check grants.",
            "retryable": True,
        }

    asyncio.run(scenario())


def test_run_create_error_includes_bootstrap_step():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(
            events,
            run_create=FakeRawTool(
                "run_create",
                {
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "RUN_CREATE_FAILED",
                        "message": "run create failed",
                        "details": {"retryable": False},
                    },
                },
                events,
            ),
        )
        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_factory=lambda **_kwargs: FakeAgent(events),
        )

        with pytest.raises(RuntimeAgentRuntimeError) as exc_info:
            await runtime.run(AgentRunRequest(datasource_id="ds_1", question="질문"))

        assert exc_info.value.details == {
            "bootstrap_step": "run_create",
            "backend_code": "RUN_CREATE_FAILED",
            "backend_message": "run create failed",
            "retryable": False,
        }

    asyncio.run(scenario())
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_datasource_bootstrap_error_includes_step_and_backend_details tests/test_agent_layer.py::test_run_create_error_includes_bootstrap_step -q
```

Expected: FAIL because backend errors are currently string-only.

- [ ] **Step 3: backend error details helper 추가**

In `src/data_agent_agent/runtime.py`, replace `_backend_error_message()` with:

```python
def _backend_error_details(step: str, result: dict[str, Any]) -> dict[str, Any]:
    error = result.get("error") or {}
    details = dict(error.get("details") or {})
    payload = {
        "bootstrap_step": step,
        "backend_code": error.get("code", "UNKNOWN_ERROR"),
        "backend_message": error.get("message", ""),
    }
    for key in ("suggestion", "retryable", "query_artifact_id"):
        if key in details:
            payload[key] = details[key]
    return payload


def _backend_error_message(step: str, result: dict[str, Any]) -> str:
    details = _backend_error_details(step, result)
    return f"{step} 실패: {details['backend_code']} - {details['backend_message']}"


def _raise_backend_runtime_error(step: str, result: dict[str, Any]) -> None:
    raise AgentRuntimeError(_backend_error_message(step, result), _backend_error_details(step, result))
```

- [ ] **Step 4: resolve/run_create 실패 지점에 helper 적용**

Update `resolve_datasource_id()`:

```python
    listed = await call_raw_tool(raw_tools["datasource_list"], {})
    if not listed.get("ok"):
        _raise_backend_runtime_error("datasource_list", listed)
```

Apply the same replacement to `datasource_create`, `datasource_test`, and `datasource_refresh_catalog` failures.

Update `_create_run()`:

```python
        run_result = await call_raw_tool(raw_tools["run_create"], {"metadata": metadata})
        if not run_result.get("ok"):
            _raise_backend_runtime_error("run_create", run_result)
```

- [ ] **Step 5: tests 통과 확인**

Run:

```powershell
uv run pytest tests/test_agent_layer.py -q
```

Expected: PASS.

- [ ] **Step 6: 커밋**

```powershell
git add tests/test_agent_layer.py src/data_agent_agent/runtime.py
git commit -m "Add bootstrap error details"
```

## Task 6: trace/run metadata 규칙 고정

**Files:**
- Modify: `tests/test_agent_layer.py`
- Modify: `src/data_agent_agent/runtime.py`

- [ ] **Step 1: trace_name과 model metadata 테스트 추가**

Append to `tests/test_agent_layer.py`:

```python
def test_run_metadata_includes_model_and_trace_name():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key", openai_model="gpt-test"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_factory=lambda **_kwargs: FakeAgent(events),
        )

        await runtime.run(AgentRunRequest(datasource_id="ds_1", question="질문", source="data-agent-api"))

        metadata = events[0][1]["metadata"]
        assert metadata["source"] == "data-agent-api"
        assert metadata["model"] == "gpt-test"
        assert metadata["trace_name"] == "data-agent:data-agent-api:ds_1:run_1"

    asyncio.run(scenario())
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_run_metadata_includes_model_and_trace_name -q
```

Expected: FAIL because run metadata currently does not include `model` or `trace_name`.

- [ ] **Step 3: run_create metadata 보강**

In `src/data_agent_agent/runtime.py`, change `_create_run()` to accept `config`:

```python
    async def _create_run(
        self,
        raw_tools: dict[str, Any],
        *,
        request: AgentRunRequest,
        datasource_id: str,
        datasource_source: str,
        config: AgentConfig,
    ) -> str:
```

Update the call site in `AgentRuntime.run()`:

```python
        run_id = await self._create_run(
            raw_tools,
            request=request,
            datasource_id=resolved_datasource_id,
            datasource_source=datasource_source,
            config=config,
        )
```

Inside `_create_run()`, include `model` and a pre-run trace name:

```python
        metadata = {
            **request.metadata,
            "source": request.source,
            "datasource_source": datasource_source,
            "datasource_id": datasource_id,
            "question": request.question,
            "model": config.openai_model,
            "trace_name": self._trace_name(request.source, datasource_id, "pending"),
        }
```

Use `pending` in run metadata because the run id does not exist until `run_create` succeeds. Agent adapter metadata already uses the exact `run_id`.

Set the test expectation to:

```python
        assert metadata["trace_name"] == "data-agent:data-agent-api:ds_1:pending"
```

- [ ] **Step 4: agent adapter metadata exact trace 확인**

Add this assertion to `test_agent_runtime_uses_agent_runner_adapter`:

```python
        assert events[1][1]["metadata"]["trace_name"] == "data-agent:data-agent-agent:ds_1:run_1"
```

- [ ] **Step 5: tests 통과 확인**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_run_metadata_includes_model_and_trace_name tests/test_agent_layer.py::test_agent_runtime_uses_agent_runner_adapter -q
```

Expected: PASS.

- [ ] **Step 6: 커밋**

```powershell
git add tests/test_agent_layer.py src/data_agent_agent/runtime.py
git commit -m "Add trace metadata to agent runs"
```

## Task 7: normalize_tool_result 입력 형태 보강

**Files:**
- Modify: `tests/test_agent_layer.py`
- Modify: `src/data_agent_agent/tools.py`

- [ ] **Step 1: normalize_tool_result edge case 테스트 추가**

Append to `tests/test_agent_layer.py`:

```python
def test_normalize_tool_result_preserves_failure_envelope_dict():
    result = normalize_tool_result(
        {
            "ok": False,
            "data": None,
            "error": {
                "code": "POLICY_BLOCKED",
                "message": "Blocked.",
                "details": {"decision_id": "pd_1"},
            },
        }
    )

    assert result == {
        "ok": False,
        "data": None,
        "error": {
            "code": "POLICY_BLOCKED",
            "message": "Blocked.",
            "details": {"decision_id": "pd_1"},
        },
    }


def test_normalize_tool_result_handles_model_dump_object():
    class Dumpable:
        def model_dump(self, mode):
            assert mode == "json"
            return {"ok": True, "data": {"value": 1}, "error": None}

    assert normalize_tool_result(Dumpable()) == {"ok": True, "data": {"value": 1}, "error": None}


def test_normalize_tool_result_wraps_plain_string():
    assert normalize_tool_result("plain output") == {"ok": True, "data": "plain output", "error": None}
```

- [ ] **Step 2: 테스트 실행**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_normalize_tool_result_preserves_failure_envelope_dict tests/test_agent_layer.py::test_normalize_tool_result_handles_model_dump_object tests/test_agent_layer.py::test_normalize_tool_result_wraps_plain_string -q
```

Expected: Existing implementation may already PASS. If it fails, fix only `normalize_tool_result()`.

- [ ] **Step 3: normalize_tool_result 구현을 계약 코드와 대조**

Update `src/data_agent_agent/tools.py` only when the current function differs from this implementation shape:

```python
def normalize_tool_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        result = result.model_dump(mode="json")
    if isinstance(result, list):
        if len(result) == 1 and isinstance(result[0], dict) and result[0].get("type") == "text":
            text = result[0].get("text")
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    return {"ok": True, "data": text, "error": None}
                return normalize_tool_result(parsed)
        return {"ok": True, "data": result, "error": None}
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return {"ok": True, "data": result, "error": None}
        result = parsed
    if isinstance(result, dict):
        if "ok" in result:
            return result
        return {"ok": True, "data": result, "error": None}
    return {"ok": True, "data": result, "error": None}
```

- [ ] **Step 4: tests 통과 확인**

Run:

```powershell
uv run pytest tests/test_agent_layer.py -q
```

Expected: PASS.

- [ ] **Step 5: 커밋**

```powershell
git add tests/test_agent_layer.py src/data_agent_agent/tools.py
git commit -m "Cover backend tool result normalization"
```

## Task 8: CLI 오류 출력 개선

**Files:**
- Modify: `tests/test_agent_layer.py`
- Modify: `src/data_agent_agent/runner.py`

- [ ] **Step 1: CLI error formatting helper 테스트 추가**

Append to `tests/test_agent_layer.py`:

```python
def test_format_cli_error_includes_bootstrap_step_and_suggestion():
    from data_agent_agent.runner import format_cli_error

    exc = RuntimeAgentRuntimeError(
        "datasource_test 실패: DATASOURCE_CONNECTION_ERROR - Datasource connection failed.",
        details={
            "bootstrap_step": "datasource_test",
            "suggestion": "Check credentials.",
            "retryable": True,
        },
    )

    message = format_cli_error(exc)

    assert "datasource_test" in message
    assert "Check credentials." in message
    assert "재시도 가능" in message
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_format_cli_error_includes_bootstrap_step_and_suggestion -q
```

Expected: FAIL because `format_cli_error()` does not exist.

- [ ] **Step 3: runner.py에 helper 추가**

Add to `src/data_agent_agent/runner.py`:

```python
def format_cli_error(exc: Exception) -> str:
    details = getattr(exc, "details", {}) or {}
    parts = [str(exc)]
    bootstrap_step = details.get("bootstrap_step")
    if bootstrap_step:
        parts.append(f"단계: {bootstrap_step}")
    suggestion = details.get("suggestion")
    if suggestion:
        parts.append(f"제안: {suggestion}")
    if details.get("retryable") is True:
        parts.append("재시도 가능: 예")
    elif details.get("retryable") is False:
        parts.append("재시도 가능: 아니오")
    return " | ".join(parts)
```

Update `main()` error handling:

```python
    except (AgentConfigError, BackendMCPToolError, AgentRuntimeError) as exc:
        print(f"오류: {format_cli_error(exc)}", file=sys.stderr)
        raise SystemExit(1) from exc
```

- [ ] **Step 4: tests 통과 확인**

Run:

```powershell
uv run pytest tests/test_agent_layer.py -q
```

Expected: PASS.

- [ ] **Step 5: 커밋**

```powershell
git add tests/test_agent_layer.py src/data_agent_agent/runner.py
git commit -m "Improve CLI agent error formatting"
```

## Task 9: 전체 회귀 검증

**Files:**
- Modify only if previous tasks exposed a failing test that requires a focused fix.

- [ ] **Step 1: 전체 테스트 실행**

Run:

```powershell
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 2: MCP registration smoke 실행**

Run:

```powershell
uv run pytest tests/test_mcp_server.py::test_create_mcp_server_registers_tools_without_schema_error -q
```

Expected: PASS.

- [ ] **Step 3: HTTP envelope smoke 실행**

Run:

```powershell
uv run pytest tests/test_http_api.py::test_validation_errors_use_tool_result_envelope tests/test_http_api.py::test_agent_ask_endpoint_preserves_runtime_error_details -q
```

Expected: PASS.

- [ ] **Step 4: git 상태 확인**

Run:

```powershell
git status --short
```

Expected: Only intentional tracked changes from this hardening work should appear. Existing unrelated `AGENTS.md` and `Backend.code-workspace` changes may still appear and must not be included in hardening commits.

- [ ] **Step 5: 최종 수정 커밋 확인**

Run this only when Step 1 exposed final focused fixes:

```powershell
git add tests src
git commit -m "Stabilize contract runtime hardening"
```

Expected: No commit is needed if all previous task commits already captured every change.

## Self-Review

Spec coverage:

- `ToolResult` 계약: Task 1
- MCP public wrapper와 `_impl(..., services)` 패턴: Task 2
- HTTP `/agent/ask` details 보존: Task 3
- Agent runtime adapter 경계: Task 4
- datasource bootstrap 단계와 details: Task 5
- trace/run metadata: Task 6
- raw tool result normalization: Task 7
- CLI 사용자 오류 메시지: Task 8
- 전체 회귀 검증: Task 9

Placeholder scan:

- 이 계획에는 빈 작업, 확정되지 않은 항목, 구현 세부가 빠진 예외 처리 지시가 없다.

Type consistency:

- `AgentConfigError(message, details=None)`와 `AgentRuntimeError(message, details=None)`는 API route, CLI formatter, tests에서 같은 속성명 `details`를 사용한다.
- `AgentRunner.run()`은 `question`, `model`, `tools`, `metadata` 키워드 인자를 사용하고 `{"answer": ..., "raw_result": ...}`를 반환한다.
- `trace_name`은 run metadata에서는 `pending`, agent adapter metadata에서는 실제 `run_id`를 사용한다.
