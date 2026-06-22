# MCP Tool Wrapper Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FastMCP에 공개되는 MCP 도구 함수의 입력 스키마에서 내부 `services` 주입 파라미터를 제거하면서, HTTP API와 테스트에서는 명시적 `BackendServices` 주입을 계속 사용할 수 있게 만든다.

**Architecture:** 각 `mcp/tools_*.py` 모듈은 외부 공개 함수와 내부 `_impl` 함수를 분리한다. 공개 함수는 MCP 클라이언트가 넘길 수 있는 JSON 직렬화 가능한 인자만 받고 `get_services()`로 기본 서비스를 가져오며, 내부 함수는 `services: BackendServices`를 필수 keyword-only 인자로 받아 API 라우터와 테스트에서 재사용한다.

**Tech Stack:** Python 3.11, FastMCP, Pydantic v2, FastAPI, pytest, uv.

---

## 파일 구조

- 수정: `src/data_agent_backend/mcp/tools_workspace.py`
  - 공개 함수 `workspace_*`에서 `services` 파라미터 제거
  - 내부 함수 `workspace_*_impl` 추가
- 수정: `src/data_agent_backend/mcp/tools_execution.py`
  - `sql_run_query`, `sandbox_run_python` 공개 wrapper와 내부 impl 분리
- 수정: `src/data_agent_backend/mcp/tools_runs.py`
  - run 관련 MCP 도구 전체 wrapper/impl 분리
- 수정: `src/data_agent_backend/mcp/tools_datasources.py`
  - datasource 관련 MCP 도구 전체 wrapper/impl 분리
- 수정: `src/data_agent_backend/mcp/tools_artifacts.py`
  - artifact 관련 MCP 도구 전체 wrapper/impl 분리
- 수정: `src/data_agent_backend/mcp/tools_memory.py`
  - memory 관련 MCP 도구 전체 wrapper/impl 분리
- 수정: `src/data_agent_backend/mcp/tools_approvals.py`
  - approval 관련 MCP 도구 전체 wrapper/impl 분리
- 수정: `src/data_agent_backend/mcp/tools_catalog.py`
  - catalog 관련 MCP 도구 전체 wrapper/impl 분리
- 수정: `src/data_agent_backend/mcp/tools_policy.py`
  - policy 관련 MCP 도구 wrapper/impl 분리
- 수정: `src/data_agent_backend/mcp/tools_exports.py`
  - export 관련 MCP 도구 wrapper/impl 분리
- 수정: `src/data_agent_backend/api/routes_*.py`
  - 기존 공개 MCP 함수 호출을 내부 impl 함수 호출로 변경
- 수정: `tests/test_sql_sandbox_mcp.py`, `tests/test_runs.py`, `tests/test_datasources.py`
  - 기존 `services=services` 호출을 내부 impl 함수 호출로 변경
- 수정 또는 생성: `tests/test_mcp_server.py`
  - `create_mcp_server()`가 예외 없이 도구를 등록하는 회귀 테스트 추가
  - 공개 MCP 함수 signature에 `services`가 없다는 회귀 테스트 추가

---

### Task 1: Workspace 도구부터 wrapper/impl 패턴 확정

**Files:**
- Modify: `src/data_agent_backend/mcp/tools_workspace.py`
- Modify: `src/data_agent_backend/api/routes_workspace.py`
- Modify: `tests/test_sql_sandbox_mcp.py`

- [ ] **Step 1: 실패하는 signature 테스트 추가**

`tests/test_sql_sandbox_mcp.py`에 아래 테스트를 추가한다.

```python
import inspect

from data_agent_backend.mcp.tools_workspace import workspace_write_text


def test_workspace_mcp_public_signature_hides_services():
    signature = inspect.signature(workspace_write_text)
    assert "services" not in signature.parameters
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
uv run pytest tests/test_sql_sandbox_mcp.py::test_workspace_mcp_public_signature_hides_services -q
```

Expected: FAIL. 현재 공개 함수에 `services` 파라미터가 있으므로 assertion이 실패한다.

- [ ] **Step 3: `tools_workspace.py`를 wrapper/impl로 변경**

`src/data_agent_backend/mcp/tools_workspace.py`를 아래 형태로 바꾼다.

```python
from __future__ import annotations

from typing import Any

from data_agent_backend.mcp.deps import context_from, get_services, result_wrap
from data_agent_backend.models.tool_results import ToolResult
from data_agent_backend.services.factory import BackendServices


def workspace_list(path: str = "/", context: dict[str, Any] | None = None) -> ToolResult:
    return workspace_list_impl(path=path, context=context, services=get_services())


def workspace_list_impl(*, path: str = "/", context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.workspace_backend.list(path, context_from(context, "workspace_list")))


def workspace_read_text(path: str, context: dict[str, Any] | None = None) -> ToolResult:
    return workspace_read_text_impl(path=path, context=context, services=get_services())


def workspace_read_text_impl(*, path: str, context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.workspace_backend.read_text(path, context_from(context, "workspace_read_text")))


def workspace_write_text(path: str, content: str, context: dict[str, Any] | None = None) -> ToolResult:
    return workspace_write_text_impl(path=path, content=content, context=context, services=get_services())


def workspace_write_text_impl(*, path: str, content: str, context: dict[str, Any] | None = None, services: BackendServices) -> ToolResult:
    return result_wrap(lambda: services.workspace_backend.write_text(path, content, context_from(context, "workspace_write_text")))


def workspace_preview(path_or_artifact_id: str, context: dict[str, Any] | None = None) -> ToolResult:
    return workspace_preview_impl(path_or_artifact_id=path_or_artifact_id, context=context, services=get_services())


def workspace_preview_impl(
    *,
    path_or_artifact_id: str,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.workspace_backend.preview(path_or_artifact_id, context_from(context, "workspace_preview")))
```

- [ ] **Step 4: API 라우터를 impl 호출로 변경**

`src/data_agent_backend/api/routes_workspace.py` import를 아래처럼 바꾼다.

```python
from data_agent_backend.mcp.tools_workspace import (
    workspace_list_impl,
    workspace_preview_impl,
    workspace_read_text_impl,
    workspace_write_text_impl,
)
```

각 endpoint 호출은 아래처럼 keyword-only impl을 사용한다.

```python
return dump_result(workspace_list_impl(path=payload.path, context=payload.context, services=services))
return dump_result(workspace_read_text_impl(path=payload.path, context=payload.context, services=services))
return dump_result(workspace_write_text_impl(path=payload.path, content=payload.content, context=payload.context, services=services))
return dump_result(workspace_preview_impl(path_or_artifact_id=payload.path_or_artifact_id, context=payload.context, services=services))
```

- [ ] **Step 5: 테스트 호출을 impl로 변경**

`tests/test_sql_sandbox_mcp.py` import를 아래처럼 바꾼다.

```python
from data_agent_backend.mcp.tools_workspace import workspace_write_text_impl
```

기존 호출을 아래처럼 바꾼다.

```python
ok = workspace_write_text_impl(path="/workspace/a.txt", content="hello", services=services)
blocked = workspace_write_text_impl(path="/artifacts/a.txt", content="hello", services=services)
```

- [ ] **Step 6: workspace 관련 테스트 통과 확인**

Run:

```powershell
uv run pytest tests/test_sql_sandbox_mcp.py::test_workspace_mcp_public_signature_hides_services tests/test_sql_sandbox_mcp.py::test_mcp_tools_return_tool_result_envelope tests/test_http_api.py::test_workspace_write_text_and_policy_block -q
```

Expected: PASS.

---

### Task 2: 나머지 MCP 도구 모듈에 동일 패턴 적용

**Files:**
- Modify: `src/data_agent_backend/mcp/tools_execution.py`
- Modify: `src/data_agent_backend/mcp/tools_runs.py`
- Modify: `src/data_agent_backend/mcp/tools_datasources.py`
- Modify: `src/data_agent_backend/mcp/tools_artifacts.py`
- Modify: `src/data_agent_backend/mcp/tools_memory.py`
- Modify: `src/data_agent_backend/mcp/tools_approvals.py`
- Modify: `src/data_agent_backend/mcp/tools_catalog.py`
- Modify: `src/data_agent_backend/mcp/tools_policy.py`
- Modify: `src/data_agent_backend/mcp/tools_exports.py`

- [ ] **Step 1: 전체 공개 MCP 함수 signature 테스트 추가**

새 파일 `tests/test_mcp_server.py`를 만든다.

```python
from __future__ import annotations

import inspect

from data_agent_backend.mcp import tools_approvals
from data_agent_backend.mcp import tools_artifacts
from data_agent_backend.mcp import tools_catalog
from data_agent_backend.mcp import tools_datasources
from data_agent_backend.mcp import tools_execution
from data_agent_backend.mcp import tools_exports
from data_agent_backend.mcp import tools_memory
from data_agent_backend.mcp import tools_policy
from data_agent_backend.mcp import tools_runs
from data_agent_backend.mcp import tools_workspace


PUBLIC_TOOL_FUNCTIONS = [
    tools_workspace.workspace_list,
    tools_workspace.workspace_read_text,
    tools_workspace.workspace_write_text,
    tools_workspace.workspace_preview,
    tools_runs.run_create,
    tools_runs.run_get,
    tools_runs.run_list,
    tools_runs.run_update_status,
    tools_runs.run_append_event,
    tools_runs.run_list_events,
    tools_runs.run_summary,
    tools_artifacts.artifact_register,
    tools_artifacts.artifact_get,
    tools_artifacts.artifact_list,
    tools_artifacts.artifact_preview,
    tools_artifacts.artifact_lineage,
    tools_memory.memory_propose,
    tools_memory.memory_list,
    tools_memory.memory_get,
    tools_memory.memory_search,
    tools_approvals.approval_list_pending,
    tools_approvals.approval_get,
    tools_approvals.approval_resolve,
    tools_policy.policy_evaluate,
    tools_execution.sql_run_query,
    tools_execution.sandbox_run_python,
    tools_catalog.catalog_list,
    tools_catalog.catalog_get,
    tools_datasources.datasource_create,
    tools_datasources.datasource_test,
    tools_datasources.datasource_list,
    tools_datasources.datasource_refresh_catalog,
    tools_datasources.datasource_get_catalog,
    tools_datasources.datasource_get_catalog_summary,
    tools_datasources.datasource_query,
    tools_exports.export_create,
]


def test_public_mcp_tool_signatures_hide_internal_services_parameter():
    offenders = [
        fn.__name__
        for fn in PUBLIC_TOOL_FUNCTIONS
        if "services" in inspect.signature(fn).parameters
    ]
    assert offenders == []
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
uv run pytest tests/test_mcp_server.py::test_public_mcp_tool_signatures_hide_internal_services_parameter -q
```

Expected: FAIL. 아직 workspace 외 도구들에 `services` 파라미터가 남아 있다.

- [ ] **Step 3: 각 모듈에서 공개 함수와 내부 impl 분리**

모든 `tools_*.py`에서 아래 규칙을 적용한다.

```python
def public_tool(arg1: str, context: dict[str, Any] | None = None) -> ToolResult:
    return public_tool_impl(arg1=arg1, context=context, services=get_services())


def public_tool_impl(
    *,
    arg1: str,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    return result_wrap(lambda: services.target_service.method(arg1, context_from(context, "public_tool")))
```

적용 규칙:

- 공개 함수명은 기존 MCP tool 이름을 유지한다.
- 내부 함수명은 기존 함수명 뒤에 `_impl`을 붙인다.
- 내부 함수의 `services`는 `BackendServices | None`이 아니라 `BackendServices` 필수 인자로 둔다.
- 내부 함수는 keyword-only 인자(`*`)를 사용한다.
- `context_from(context, "...")`의 tool name 문자열은 기존 공개 함수명을 그대로 사용한다.

- [ ] **Step 4: 빠른 signature 테스트 통과 확인**

Run:

```powershell
uv run pytest tests/test_mcp_server.py::test_public_mcp_tool_signatures_hide_internal_services_parameter -q
```

Expected: PASS.

---

### Task 3: API 라우터와 기존 단위 테스트를 내부 impl 호출로 전환

**Files:**
- Modify: `src/data_agent_backend/api/routes_approvals.py`
- Modify: `src/data_agent_backend/api/routes_artifacts.py`
- Modify: `src/data_agent_backend/api/routes_catalog.py`
- Modify: `src/data_agent_backend/api/routes_datasources.py`
- Modify: `src/data_agent_backend/api/routes_execution.py`
- Modify: `src/data_agent_backend/api/routes_exports.py`
- Modify: `src/data_agent_backend/api/routes_memory.py`
- Modify: `src/data_agent_backend/api/routes_policy.py`
- Modify: `src/data_agent_backend/api/routes_runs.py`
- Modify: `src/data_agent_backend/api/routes_workspace.py`
- Modify: `tests/test_sql_sandbox_mcp.py`
- Modify: `tests/test_runs.py`
- Modify: `tests/test_datasources.py`

- [ ] **Step 1: API 라우터 import를 `_impl` 함수로 변경**

예시는 `routes_execution.py` 기준이다.

```python
from data_agent_backend.mcp.tools_execution import sandbox_run_python_impl, sql_run_query_impl
```

호출은 아래처럼 바꾼다.

```python
return dump_result(
    sql_run_query_impl(
        query=payload.query,
        run_id=payload.run_id,
        connection_id=payload.connection_id,
        row_limit=payload.row_limit,
        context=payload.context,
        services=services,
    )
)
```

모든 `routes_*.py`에서 같은 방식으로 기존 `services=services` 호출을 `_impl(..., services=services)` 호출로 변경한다.

- [ ] **Step 2: 테스트 import를 `_impl` 함수로 변경**

예시는 `tests/test_runs.py` 기준이다.

```python
from data_agent_backend.mcp.tools_runs import run_create_impl, run_update_status_impl
```

기존 호출을 아래처럼 바꾼다.

```python
created = run_create_impl(services=services)
invalid = run_update_status_impl(run_id="run1", status="bad", services=services)
```

`tests/test_datasources.py`, `tests/test_sql_sandbox_mcp.py`도 같은 원칙으로 변경한다.

- [ ] **Step 3: API와 직접 MCP wrapper 테스트 통과 확인**

Run:

```powershell
uv run pytest tests/test_http_api.py tests/test_runs.py tests/test_datasources.py tests/test_sql_sandbox_mcp.py -q
```

Expected: PASS.

---

### Task 4: MCP 서버 기동 회귀 테스트 추가

**Files:**
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: `create_mcp_server()` 등록 테스트 추가**

`tests/test_mcp_server.py`에 아래 테스트를 추가한다.

```python
from data_agent_backend.mcp.server import create_mcp_server


def test_create_mcp_server_registers_tools_without_schema_error():
    server = create_mcp_server()
    assert server is not None
```

- [ ] **Step 2: 실패했던 명령에 가까운 테스트 실행**

Run:

```powershell
uv run pytest tests/test_mcp_server.py -q
```

Expected: PASS. 기존 Pydantic schema error가 더 이상 발생하지 않아야 한다.

- [ ] **Step 3: 실제 CLI 엔트리포인트 smoke 확인**

Run:

```powershell
uv run data-agent-mcp --help
```

Expected: 이 명령은 FastMCP 서버 특성상 help를 출력하지 않고 서버 실행으로 들어갈 수 있다. 중요한 기준은 `SchemaError: Field "services"` 또는 `sandbox_executor` 관련 traceback이 더 이상 나오지 않는 것이다. 장시간 대기하면 `Ctrl+C`로 중단한다.

---

### Task 5: 전체 회귀 확인

**Files:**
- No direct edits

- [ ] **Step 1: 전체 테스트 실행**

Run:

```powershell
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 2: MCP 서버 직접 실행 확인**

Run:

```powershell
uv run data-agent-mcp
```

Expected: 서버가 traceback 없이 시작한다. stdio 서버이므로 프롬프트가 멈춰 보이는 것은 정상이다. 확인 후 `Ctrl+C`로 종료한다.

- [ ] **Step 3: 변경 범위 확인**

Run:

```powershell
git diff -- src/data_agent_backend/mcp src/data_agent_backend/api tests
```

Expected:

- 공개 MCP 함수 signature에서 `services` 제거
- `_impl` 함수에만 `services: BackendServices` 유지
- API 라우터와 테스트는 `_impl` 함수 사용
- 서비스 계층, 정책 로직, datasource 로직, sandbox 실행 로직은 동작 변경 없음

---

## 자체 검토

- Spec coverage: MCP 공개 스키마 문제 해결, API/테스트 services 주입 유지, MCP 서버 등록 회귀 테스트를 모두 포함한다.
- Placeholder scan: 구현 대상 파일, 함수명, 테스트 코드, 실행 명령을 명시했다.
- Type consistency: 공개 함수는 JSON 직렬화 가능한 인자만 받고, 내부 함수는 `services: BackendServices`를 필수 keyword-only 인자로 받는 규칙으로 통일한다.
