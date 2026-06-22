# Agent Runtime API Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shared Agent Runtime so the existing CLI and a new HTTP `/agent/ask` endpoint execute the same data-analysis agent flow.

**Architecture:** Extract the orchestration currently embedded in `data_agent_agent.runner.run_cli()` into `data_agent_agent.runtime.AgentRuntime`. Keep the Backend-Agent boundary as a tool contract: CLI loads tools through MCP stdio, while HTTP uses an in-process provider that calls existing MCP wrapper functions with `BackendServices` injected.

**Tech Stack:** Python 3.11, FastAPI, Pydantic dataclasses/models already in the repo, LangChain tools, DeepAgents, MCP wrapper functions, pytest.

---

## File Structure

- Create `src/data_agent_agent/runtime.py`
  - Owns `AgentRunRequest`, `AgentRunResult`, `AgentRuntime`, `AgentRuntimeError`, datasource resolution, run creation, agent invocation, and final answer extraction.

- Create `src/data_agent_agent/tool_provider.py`
  - Owns `BackendToolProvider`, `MCPBackendToolProvider`, `FunctionBackendToolProvider`, `InProcessRawTool`, and `InProcessBackendToolProvider`.
  - Keeps physical backend connection details out of `AgentRuntime`.

- Modify `src/data_agent_agent/runner.py`
  - Keeps CLI argument parsing and output.
  - Re-exports compatibility helpers where tests or users already import them.
  - Delegates execution to `AgentRuntime`.

- Create `src/data_agent_backend/api/routes_agent.py`
  - Adds `POST /agent/ask`.
  - Wraps `AgentRuntime` output in `ToolResult`.

- Modify `src/data_agent_backend/api/app.py`
  - Includes the new agent router.

- Modify `tests/test_agent_layer.py`
  - Adds runtime and provider tests.
  - Updates CLI tests to assert delegation-compatible behavior.

- Modify `tests/test_http_api.py`
  - Adds `/agent/ask` response and error envelope tests.

## Task 1: Extract Common Agent Runtime

**Files:**
- Create: `src/data_agent_agent/runtime.py`
- Modify: `tests/test_agent_layer.py`
- Modify: `src/data_agent_agent/runner.py`

- [ ] **Step 1: Add failing runtime import and explicit datasource test**

Append this test to `tests/test_agent_layer.py`.

```python
from data_agent_agent.runtime import AgentRunRequest, AgentRuntime
from data_agent_agent.tool_provider import FunctionBackendToolProvider


def test_agent_runtime_with_explicit_datasource_skips_datasource_prepare():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        def make_agent(**_kwargs):
            return FakeAgent(events)

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_factory=make_agent,
        )

        result = await runtime.run(AgentRunRequest(datasource_id="ds_1", question="질문"))

        assert result.answer == "완료"
        assert result.run_id == "run_1"
        assert result.datasource_id == "ds_1"
        assert [event[0] for event in events] == ["run_create", "agent_invoke"]
        assert events[0][1]["metadata"]["source"] == "data-agent-agent"
        assert events[0][1]["metadata"]["datasource_source"] == "cli"
        assert events[0][1]["metadata"]["datasource_id"] == "ds_1"

    asyncio.run(scenario())
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_agent_runtime_with_explicit_datasource_skips_datasource_prepare -q
```

Expected: fail with `ModuleNotFoundError` for `data_agent_agent.runtime` or `data_agent_agent.tool_provider`.

- [ ] **Step 3: Create minimal tool provider module**

Create `src/data_agent_agent/tool_provider.py`.

```python
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from data_agent_agent.config import AgentConfig
from data_agent_agent.mcp_client import load_backend_tools


RawToolLoader = Callable[[AgentConfig], Awaitable[dict[str, Any]] | dict[str, Any]]


class BackendToolProvider(Protocol):
    async def load_tools(self, config: AgentConfig) -> dict[str, Any]:
        ...


class FunctionBackendToolProvider:
    def __init__(self, loader: RawToolLoader) -> None:
        self.loader = loader

    async def load_tools(self, config: AgentConfig) -> dict[str, Any]:
        result = self.loader(config)
        if inspect.isawaitable(result):
            result = await result
        return result


class MCPBackendToolProvider:
    async def load_tools(self, config: AgentConfig) -> dict[str, Any]:
        return await load_backend_tools(config)
```

- [ ] **Step 4: Create runtime module from existing runner logic**

Create `src/data_agent_agent/runtime.py`.

```python
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from data_agent_agent.config import AgentConfig
from data_agent_agent.deep_agent import create_data_agent
from data_agent_agent.mcp_client import require_backend_tools
from data_agent_agent.tool_provider import BackendToolProvider, MCPBackendToolProvider
from data_agent_agent.tools import build_agent_tools, call_raw_tool


class AgentRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentRunRequest:
    question: str
    datasource_id: str | None = None
    model: str | None = None
    row_limit: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "data-agent-agent"


@dataclass(frozen=True)
class AgentRunResult:
    answer: str
    run_id: str
    datasource_id: str
    raw_result: Any


AgentFactory = Callable[..., Any]


class AgentRuntime:
    def __init__(
        self,
        *,
        config: AgentConfig,
        tool_provider: BackendToolProvider | None = None,
        agent_factory: AgentFactory = create_data_agent,
    ) -> None:
        self.config = config
        self.tool_provider = tool_provider or MCPBackendToolProvider()
        self.agent_factory = agent_factory

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        config = self._config_for_request(request)
        os.environ.setdefault("OPENAI_API_KEY", config.openai_api_key)
        if request.datasource_id is None:
            config.mysql_create_payload()

        raw_tools = require_backend_tools(await self.tool_provider.load_tools(config))
        resolved_datasource_id = await resolve_datasource_id(raw_tools, config, request.datasource_id)
        datasource_source = "cli" if request.datasource_id else "env"
        run_id = await self._create_run(raw_tools, request, resolved_datasource_id, datasource_source)
        tools = build_agent_tools(
            raw_tools,
            datasource_id=resolved_datasource_id,
            run_id=run_id,
            default_row_limit=config.default_row_limit,
        )
        agent = self.agent_factory(model=config.openai_model, tools=tools)
        result = agent.ainvoke({"messages": [{"role": "user", "content": request.question}]})
        if asyncio.iscoroutine(result):
            result = await result
        return AgentRunResult(
            answer=extract_final_content(result),
            run_id=run_id,
            datasource_id=resolved_datasource_id,
            raw_result=result,
        )

    def _config_for_request(self, request: AgentRunRequest) -> AgentConfig:
        model = request.model or self.config.openai_model
        row_limit = request.row_limit if request.row_limit is not None else self.config.default_row_limit
        if row_limit <= 0:
            raise AgentRuntimeError("row_limit은 1 이상의 정수여야 합니다.")
        return self.config.__class__(
            openai_api_key=self.config.openai_api_key,
            openai_model=model,
            mcp_command=self.config.mcp_command,
            mcp_args=list(self.config.mcp_args),
            default_row_limit=row_limit,
            mysql_name=self.config.mysql_name,
            mysql_host=self.config.mysql_host,
            mysql_port=self.config.mysql_port,
            mysql_database=self.config.mysql_database,
            mysql_username=self.config.mysql_username,
            mysql_password=self.config.mysql_password,
        )

    async def _create_run(
        self,
        raw_tools: dict[str, Any],
        request: AgentRunRequest,
        datasource_id: str,
        datasource_source: str,
    ) -> str:
        metadata = {
            "source": request.source,
            "datasource_source": datasource_source,
            "datasource_id": datasource_id,
            "question": request.question,
            **request.metadata,
        }
        run_result = await call_raw_tool(raw_tools["run_create"], {"metadata": metadata})
        if not run_result.get("ok"):
            raise AgentRuntimeError(_backend_error_message("run_create", run_result))
        run_id = (run_result.get("data") or {}).get("run_id")
        if not run_id:
            raise AgentRuntimeError("run_create 응답에 run_id가 없습니다.")
        return str(run_id)


async def resolve_datasource_id(raw_tools: dict[str, Any], config: AgentConfig, explicit_datasource_id: str | None) -> str:
    if explicit_datasource_id:
        return explicit_datasource_id

    mysql_payload = config.mysql_create_payload()
    listed = await call_raw_tool(raw_tools["datasource_list"], {})
    if not listed.get("ok"):
        raise AgentRuntimeError(_backend_error_message("datasource_list", listed))

    existing_datasource_id = _find_matching_mysql_datasource(listed.get("data"), mysql_payload)
    datasource_id = existing_datasource_id
    if datasource_id is None:
        created = await call_raw_tool(raw_tools["datasource_create"], mysql_payload)
        if not created.get("ok"):
            raise AgentRuntimeError(_backend_error_message("datasource_create", created))
        datasource_id = (created.get("data") or {}).get("datasource_id")
        if not datasource_id:
            raise AgentRuntimeError("datasource_create 응답에 datasource_id가 없습니다.")

    tested = await call_raw_tool(raw_tools["datasource_test"], {"datasource_id": datasource_id})
    if not tested.get("ok"):
        raise AgentRuntimeError(_backend_error_message("datasource_test", tested))
    test_data = tested.get("data") or {}
    if test_data.get("ok") is False:
        message = test_data.get("message") or "Datasource connection test failed."
        raise AgentRuntimeError(f"datasource_test 실패: {message}")

    refreshed = await call_raw_tool(raw_tools["datasource_refresh_catalog"], {"datasource_id": datasource_id})
    if not refreshed.get("ok"):
        raise AgentRuntimeError(_backend_error_message("datasource_refresh_catalog", refreshed))

    return str(datasource_id)


def _find_matching_mysql_datasource(data: Any, expected: dict[str, object]) -> str | None:
    datasources = data.get("datasources") if isinstance(data, dict) else data
    if not isinstance(datasources, list):
        return None

    for datasource in datasources:
        if not isinstance(datasource, dict):
            continue
        if (
            datasource.get("kind") == "mysql"
            and datasource.get("name") == expected["name"]
            and datasource.get("host") == expected["host"]
            and datasource.get("port") == expected["port"]
            and datasource.get("database") == expected["database"]
            and datasource.get("username") == expected["username"]
        ):
            datasource_id = datasource.get("datasource_id")
            if datasource_id:
                return str(datasource_id)
    return None


def _backend_error_message(action: str, result: dict[str, Any]) -> str:
    error = result.get("error") or {}
    code = error.get("code", "UNKNOWN_ERROR")
    message = error.get("message", "")
    return f"{action} 실패: {code} - {message}"


def extract_final_content(result: Any) -> str:
    messages = result.get("messages") if isinstance(result, dict) else None
    if not messages:
        return str(result)
    last = messages[-1]
    if hasattr(last, "content"):
        return str(last.content)
    if isinstance(last, dict):
        return str(last.get("content", ""))
    return str(last)
```

- [ ] **Step 5: Update fake agent expected answer to Korean plain text**

In `tests/test_agent_layer.py`, change `FakeAgent.ainvoke()` to return `"완료"` instead of the currently mojibake text.

```python
class FakeAgent:
    def __init__(self, events):
        self.events = events

    async def ainvoke(self, payload):
        self.events.append(("agent_invoke", payload))
        return {"messages": [{"role": "assistant", "content": "완료"}]}
```

- [ ] **Step 6: Run the new runtime test**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_agent_runtime_with_explicit_datasource_skips_datasource_prepare -q
```

Expected: pass.

- [ ] **Step 7: Commit Task 1**

Run:

```powershell
git add src/data_agent_agent/runtime.py src/data_agent_agent/tool_provider.py tests/test_agent_layer.py
git commit -m "Add shared agent runtime"
```

## Task 2: Move CLI Adapter Onto Runtime

**Files:**
- Modify: `src/data_agent_agent/runner.py`
- Modify: `tests/test_agent_layer.py`

- [ ] **Step 1: Add failing compatibility assertion for `run_cli()`**

Update `test_run_create_is_called_before_agent_invoke` in `tests/test_agent_layer.py` so it keeps using `run_cli()` but expects the runtime result to include `datasource_id`.

```python
assert result.answer == "완료"
assert result.run_id == "run_1"
assert result.datasource_id == "ds_1"
```

This requires importing `AgentRunResult` from `data_agent_agent.runtime` through `runner.py` compatibility exports.

- [ ] **Step 2: Run the compatibility test**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_run_create_is_called_before_agent_invoke -q
```

Expected: fail because `runner.AgentRunResult` does not yet expose `datasource_id` or `run_cli()` has not been delegated.

- [ ] **Step 3: Refactor `runner.py` into a thin adapter**

Replace the orchestration-specific imports and duplicated functions in `src/data_agent_agent/runner.py` with runtime/provider imports. Keep `build_parser()`, `parse_args()`, and `main()`.

```python
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any, Awaitable, Callable, Sequence

from data_agent_agent.config import AgentConfig, AgentConfigError
from data_agent_agent.deep_agent import create_data_agent
from data_agent_agent.mcp_client import BackendMCPToolError, load_backend_tools
from data_agent_agent.runtime import (
    AgentRunRequest,
    AgentRunResult,
    AgentRuntime,
    AgentRuntimeError,
    extract_final_content,
    resolve_datasource_id,
)
from data_agent_agent.tool_provider import FunctionBackendToolProvider, MCPBackendToolProvider


LoadToolsFunc = Callable[[AgentConfig], Awaitable[dict[str, Any]]]
AgentFactory = Callable[..., Any]
```

Then implement `run_cli()` as:

```python
async def run_cli(
    *,
    datasource_id: str | None = None,
    question: str,
    model: str | None = None,
    row_limit: int | None = None,
    config: AgentConfig | None = None,
    load_tools_func: LoadToolsFunc = load_backend_tools,
    agent_factory: AgentFactory = create_data_agent,
) -> AgentRunResult:
    config = config or AgentConfig.from_env(openai_model=model, default_row_limit=row_limit)
    runtime = AgentRuntime(
        config=config,
        tool_provider=FunctionBackendToolProvider(load_tools_func)
        if load_tools_func is not load_backend_tools
        else MCPBackendToolProvider(),
        agent_factory=agent_factory,
    )
    return await runtime.run(
        AgentRunRequest(
            datasource_id=datasource_id,
            question=question,
            model=model,
            row_limit=row_limit,
            source="data-agent-agent",
        )
    )
```

Keep `main()` output unchanged except it may now print `result.run_id` from the runtime result.

- [ ] **Step 4: Run existing agent layer tests**

Run:

```powershell
uv run pytest tests/test_agent_layer.py -q
```

Expected: pass.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add src/data_agent_agent/runner.py tests/test_agent_layer.py
git commit -m "Route CLI through shared agent runtime"
```

## Task 3: Add In-Process Backend Tool Provider

**Files:**
- Modify: `src/data_agent_agent/tool_provider.py`
- Modify: `tests/test_agent_layer.py`

- [ ] **Step 1: Add failing in-process provider test**

Append this test to `tests/test_agent_layer.py`.

```python
def test_in_process_backend_tool_provider_exposes_required_tools(services):
    async def scenario():
        from data_agent_agent.mcp_client import REQUIRED_BACKEND_TOOLS
        from data_agent_agent.tool_provider import InProcessBackendToolProvider

        provider = InProcessBackendToolProvider(services)
        raw_tools = await provider.load_tools(AgentConfig(openai_api_key="test-key"))

        assert REQUIRED_BACKEND_TOOLS <= set(raw_tools)
        result = await raw_tools["run_create"].ainvoke({"metadata": {"source": "test"}})
        assert result["ok"] is True
        assert result["data"]["run_id"].startswith("run_")

    asyncio.run(scenario())
```

- [ ] **Step 2: Run the failing provider test**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_in_process_backend_tool_provider_exposes_required_tools -q
```

Expected: fail because `InProcessBackendToolProvider` does not exist.

- [ ] **Step 3: Implement in-process raw tool adapter**

Append to `src/data_agent_agent/tool_provider.py`.

```python
from data_agent_backend.mcp.tools_analysis_context import analysis_build_context
from data_agent_backend.mcp.tools_datasources import (
    datasource_create,
    datasource_get_catalog_summary,
    datasource_list,
    datasource_query,
    datasource_refresh_catalog,
    datasource_test,
)
from data_agent_backend.mcp.tools_runs import run_create
from data_agent_backend.services.factory import BackendServices


class InProcessRawTool:
    def __init__(self, name: str, fn: Callable[..., Any], services: BackendServices) -> None:
        self.name = name
        self.fn = fn
        self.services = services

    async def ainvoke(self, payload: dict[str, Any]) -> Any:
        result = self.fn(**payload, services=self.services)
        if inspect.isawaitable(result):
            result = await result
        return result


class InProcessBackendToolProvider:
    def __init__(self, services: BackendServices) -> None:
        self.services = services

    async def load_tools(self, _config: AgentConfig) -> dict[str, Any]:
        tools = {
            "run_create": run_create,
            "datasource_list": datasource_list,
            "datasource_create": datasource_create,
            "datasource_test": datasource_test,
            "datasource_refresh_catalog": datasource_refresh_catalog,
            "datasource_get_catalog_summary": datasource_get_catalog_summary,
            "analysis_build_context": analysis_build_context,
            "datasource_query": datasource_query,
        }
        return {
            name: InProcessRawTool(name, fn, self.services)
            for name, fn in tools.items()
        }
```

- [ ] **Step 4: Run provider test**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_in_process_backend_tool_provider_exposes_required_tools -q
```

Expected: pass.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add src/data_agent_agent/tool_provider.py tests/test_agent_layer.py
git commit -m "Add in-process backend tool provider"
```

## Task 4: Add HTTP `/agent/ask` Endpoint

**Files:**
- Create: `src/data_agent_backend/api/routes_agent.py`
- Modify: `src/data_agent_backend/api/app.py`
- Modify: `tests/test_http_api.py`

- [ ] **Step 1: Add failing HTTP success test with fake runtime**

Append this test to `tests/test_http_api.py`.

```python
def test_agent_ask_endpoint_returns_tool_result(monkeypatch, services):
    from data_agent_agent.runtime import AgentRunResult

    class FakeRuntime:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def run(self, request):
            assert request.question == "월별 주문 수"
            assert request.datasource_id == "ds_1"
            assert request.row_limit == 50
            assert request.metadata == {"ui": "prototype"}
            return AgentRunResult(answer="월별 주문 수 답변", run_id="run_1", datasource_id="ds_1", raw_result={})

    monkeypatch.setattr("data_agent_backend.api.routes_agent.AgentRuntime", FakeRuntime)

    response = client_for(services).post(
        "/agent/ask",
        json={
            "question": "월별 주문 수",
            "datasource_id": "ds_1",
            "row_limit": 50,
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
```

- [ ] **Step 2: Run the failing HTTP test**

Run:

```powershell
uv run pytest tests/test_http_api.py::test_agent_ask_endpoint_returns_tool_result -q
```

Expected: fail with 404 or import error for `routes_agent`.

- [ ] **Step 3: Create route module**

Create `src/data_agent_backend/api/routes_agent.py`.

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from data_agent_agent.config import AgentConfig, AgentConfigError
from data_agent_agent.runtime import AgentRunRequest, AgentRuntime, AgentRuntimeError
from data_agent_agent.tool_provider import InProcessBackendToolProvider
from data_agent_backend.api.common import dump_result
from data_agent_backend.models.common import BackendModel, JsonDict
from data_agent_backend.models.tool_results import ToolResult
from data_agent_backend.services.factory import BackendServices

from .deps import get_backend_services


router = APIRouter(prefix="/agent", tags=["agent"])


class AgentAskPayload(BackendModel):
    question: str
    datasource_id: str | None = None
    model: str | None = None
    row_limit: int | None = None
    metadata: JsonDict = {}


@router.post("/ask")
async def ask_agent(payload: AgentAskPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    try:
        config = AgentConfig.from_env(
            openai_model=payload.model,
            default_row_limit=payload.row_limit,
            load_env=True,
        )
        runtime = AgentRuntime(
            config=config,
            tool_provider=InProcessBackendToolProvider(services),
        )
        result = await runtime.run(
            AgentRunRequest(
                question=payload.question,
                datasource_id=payload.datasource_id,
                model=payload.model,
                row_limit=payload.row_limit,
                metadata=payload.metadata,
                source="data-agent-api",
            )
        )
        return dump_result(
            ToolResult.success(
                {
                    "answer": result.answer,
                    "run_id": result.run_id,
                    "datasource_id": result.datasource_id,
                }
            )
        )
    except AgentConfigError as exc:
        return dump_result(ToolResult.failure("AGENT_CONFIG_ERROR", str(exc)))
    except AgentRuntimeError as exc:
        return dump_result(ToolResult.failure("AGENT_RUNTIME_ERROR", str(exc)))
    except Exception as exc:
        return dump_result(ToolResult.failure("AGENT_RUNTIME_ERROR", str(exc)))
```

- [ ] **Step 4: Include route in app**

Modify `src/data_agent_backend/api/app.py`.

Add import:

```python
from data_agent_backend.api.routes_agent import router as agent_router
```

Add before the other routers or near them:

```python
app.include_router(agent_router)
```

- [ ] **Step 5: Run HTTP success test**

Run:

```powershell
uv run pytest tests/test_http_api.py::test_agent_ask_endpoint_returns_tool_result -q
```

Expected: pass.

- [ ] **Step 6: Commit Task 4**

Run:

```powershell
git add src/data_agent_backend/api/routes_agent.py src/data_agent_backend/api/app.py tests/test_http_api.py
git commit -m "Add agent ask HTTP endpoint"
```

## Task 5: Normalize HTTP Runtime Errors

**Files:**
- Modify: `tests/test_http_api.py`
- Modify: `src/data_agent_backend/api/routes_agent.py`

- [ ] **Step 1: Add failing HTTP error envelope test**

Append this test to `tests/test_http_api.py`.

```python
def test_agent_ask_endpoint_returns_error_envelope(monkeypatch, services):
    from data_agent_agent.runtime import AgentRuntimeError

    class FakeRuntime:
        def __init__(self, **_kwargs):
            pass

        async def run(self, _request):
            raise AgentRuntimeError("agent failed")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("data_agent_backend.api.routes_agent.AgentRuntime", FakeRuntime)

    body = client_for(services).post("/agent/ask", json={"question": "질문", "datasource_id": "ds_1"}).json()

    assert body["ok"] is False
    assert body["error"]["code"] == "AGENT_RUNTIME_ERROR"
    assert body["error"]["message"] == "agent failed"
```

- [ ] **Step 2: Run error test**

Run:

```powershell
uv run pytest tests/test_http_api.py::test_agent_ask_endpoint_returns_error_envelope -q
```

Expected: pass if Task 4 error handling is already correct. If it fails, adjust `routes_agent.py` to catch `AgentRuntimeError` before generic `Exception`.

- [ ] **Step 3: Add config error test**

Append this test to `tests/test_http_api.py`.

```python
def test_agent_ask_endpoint_reports_missing_openai_key(monkeypatch, services):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    body = client_for(services).post("/agent/ask", json={"question": "질문", "datasource_id": "ds_1"}).json()

    assert body["ok"] is False
    assert body["error"]["code"] == "AGENT_CONFIG_ERROR"
    assert "OPENAI_API_KEY" in body["error"]["message"]
```

- [ ] **Step 4: Run agent HTTP tests**

Run:

```powershell
uv run pytest tests/test_http_api.py::test_agent_ask_endpoint_returns_tool_result tests/test_http_api.py::test_agent_ask_endpoint_returns_error_envelope tests/test_http_api.py::test_agent_ask_endpoint_reports_missing_openai_key -q
```

Expected: pass.

- [ ] **Step 5: Commit Task 5**

Run:

```powershell
git add src/data_agent_backend/api/routes_agent.py tests/test_http_api.py
git commit -m "Normalize agent API errors"
```

## Task 6: Regression and Import Coverage

**Files:**
- Modify: `tests/test_agent_layer.py`
- Modify: `tests/test_http_api.py` only if route import coverage needs adjustment

- [ ] **Step 1: Update import smoke test**

Modify `test_agent_layer_import_smoke` in `tests/test_agent_layer.py`.

```python
def test_agent_layer_import_smoke():
    import data_agent_agent.config
    import data_agent_agent.deep_agent
    import data_agent_agent.runner
    import data_agent_agent.runtime
    import data_agent_agent.tool_provider
    import data_agent_agent.tools

    assert data_agent_agent.config.DEFAULT_OPENAI_MODEL == DEFAULT_OPENAI_MODEL
```

- [ ] **Step 2: Run targeted regression tests**

Run:

```powershell
uv run pytest tests/test_agent_layer.py tests/test_http_api.py -q
```

Expected: pass.

- [ ] **Step 3: Run full suite**

Run:

```powershell
uv run pytest -q
```

Expected: pass. If unrelated existing datasource connector changes fail tests, inspect the failure and separate prototype changes from pre-existing worktree changes before committing any fix.

- [ ] **Step 4: Inspect diff scope**

Run:

```powershell
git status --short
git diff --stat
```

Expected prototype files:

```text
src/data_agent_agent/runtime.py
src/data_agent_agent/tool_provider.py
src/data_agent_agent/runner.py
src/data_agent_backend/api/routes_agent.py
src/data_agent_backend/api/app.py
tests/test_agent_layer.py
tests/test_http_api.py
```

Pre-existing unrelated modified files should remain unstaged unless a task intentionally touches them:

```text
src/data_agent_backend/services/connectors/base.py
src/data_agent_backend/services/connectors/mysql.py
src/data_agent_backend/services/datasource_service.py
tests/test_datasources.py
```

- [ ] **Step 5: Commit Task 6**

Run:

```powershell
git add tests/test_agent_layer.py
git commit -m "Cover agent runtime imports"
```

Skip this commit if Step 1 was already included in an earlier task commit.

## Self-Review

- Spec coverage: shared runtime, CLI adapter, HTTP adapter, MCP stdio provider, in-process provider, datasource preparation, run metadata, ToolResult HTTP envelope, and fake tests are each covered by tasks.
- Placeholder scan: every task has concrete files, code snippets, commands, and expected results.
- Type consistency: `AgentRunRequest`, `AgentRunResult`, `AgentRuntime`, `AgentRuntimeError`, `FunctionBackendToolProvider`, `MCPBackendToolProvider`, and `InProcessBackendToolProvider` are introduced before later tasks reference them.
- Scope check: background runs, streaming, UI, real OpenAI integration tests, and agent graph rewrites remain excluded.
