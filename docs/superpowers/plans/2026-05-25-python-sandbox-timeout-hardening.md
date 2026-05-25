# Python Sandbox Timeout Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Python 샌드박스 실행에 기본 5분/최대 10분 timeout, 호출별 override, 시작/종료 로그, agent 프롬프트 기반 1회 재시도, 분석 패키지 extra를 추가한다.

**Architecture:** timeout 정책은 backend sandbox executor 경계에서 최종 검증하고, API/MCP/agent/CLI는 값을 전달만 한다. agent 재시도는 DeepAgents system prompt 규칙으로 처리하며, backend는 Python 코드 수정이나 prelude 주입을 하지 않는다.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, MCP tool wrapper, DeepAgents/LangChain tools, pytest, subprocess, SQLite-backed artifact registry.

---

## File Structure

- Modify `src/data_agent_backend/config.py`
  - `default_execution_timeout_ms=300_000`, `max_execution_timeout_ms=600_000` 설정을 둔다.
- Modify `src/data_agent_backend/models/execution.py`
  - `ExecutionLimits.timeout_ms`를 호출별 선택값으로 바꾼다.
- Modify `src/data_agent_backend/services/sandbox_executor.py`
  - timeout 검증, effective timeout 계산, 시작/종료 로그 파일 생성, local/docker timeout 전달을 담당한다.
- Modify `src/data_agent_backend/mcp/tools_execution.py`
  - `sandbox_run_python` public/impl 함수에 `timeout_ms`를 추가한다.
- Modify `src/data_agent_backend/api/routes_execution.py`
  - `/execution/python` request model에 `timeout_ms`를 추가한다.
- Modify `src/data_agent_agent/tools.py`
  - agent `run_python` tool이 `timeout_ms`를 받고 raw backend tool에 전달한다.
- Modify `src/data_agent_agent/runtime.py`
  - `AgentRunRequest.python_timeout_ms`를 받아 `build_agent_tools()`로 전달한다.
- Modify `src/data_agent_agent/runner.py`
  - CLI `--python-timeout-ms` 옵션을 추가한다.
- Modify `src/data_agent_backend/api/routes_agent.py`
  - HTTP agent request가 `python_timeout_ms`를 받을 수 있게 한다.
- Modify `src/data_agent_agent/prompts/system.md`
  - Python 일반 오류 1회 재시도, timeout 재시도 금지 규칙을 추가한다.
- Modify `pyproject.toml`
  - `analysis` optional dependency에 `pandas`, `matplotlib`, `seaborn`을 추가한다.
- Modify `tests/test_sql_sandbox_mcp.py`
  - backend timeout 정책, validation, 시작/종료 로그 테스트를 추가한다.
- Modify `tests/test_agent_layer.py`
  - agent tool/runtime/CLI timeout 전달과 prompt 규칙 테스트를 추가한다.
- Modify `tests/test_http_api.py`
  - `/execution/python`, `/agent/ask` timeout 전달 테스트를 추가한다.
- Modify `tests/test_mcp_server.py`
  - MCP public signature에 `timeout_ms`가 노출되고 `services`는 숨겨지는지 확인한다.

## Scope Check

이 계획은 단일 하위 시스템인 Python sandbox 실행 안정화만 다룬다. SQL 쿼리 성능, Python 코드 자동 수정 로직, prelude 주입, 정적 검사, streaming 로그, background job/cancel API는 포함하지 않는다.

---

### Task 1: Backend Timeout Policy Tests

**Files:**
- Modify: `tests/test_sql_sandbox_mcp.py`
- Modify: `src/data_agent_backend/config.py`
- Modify: `src/data_agent_backend/models/execution.py`
- Modify: `src/data_agent_backend/services/sandbox_executor.py`

- [ ] **Step 1: Write failing tests for default and max timeout config**

Add these tests near existing sandbox timeout tests in `tests/test_sql_sandbox_mcp.py`.

```python
def test_python_execution_limits_default_to_configured_timeout():
    config = BackendConfig()

    assert config.default_execution_timeout_ms == 300_000
    assert config.max_execution_timeout_ms == 600_000
    assert ExecutionLimits().timeout_ms is None


def test_docker_sandbox_default_run_uses_configured_timeout(services):
    class CapturingDockerProvider:
        def __init__(self):
            self.timeout_ms = None

        def run(self, request):
            self.timeout_ms = request.timeout_ms
            return DockerSandboxRunResult(exit_code=0, stdout="ok\n", stderr="", runtime_ms=12)

    provider = CapturingDockerProvider()
    executor = DockerSandboxExecutor(
        services.config,
        services.policy_engine,
        services.artifact_registry,
        services.artifact_store,
        provider=provider,
    )

    result = executor.run_python(
        "print('ok')",
        [],
        ExecutionLimits(),
        PolicyContext(run_id="run1", approval_id="approved"),
    )

    assert result.status == ExecutionStatus.success
    assert provider.timeout_ms == services.config.default_execution_timeout_ms
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
uv run pytest tests/test_sql_sandbox_mcp.py::test_python_execution_limits_default_to_configured_timeout tests/test_sql_sandbox_mcp.py::test_docker_sandbox_default_run_uses_configured_timeout -q
```

Expected: FAIL because `max_execution_timeout_ms` does not exist and `ExecutionLimits().timeout_ms` is still `30_000`.

- [ ] **Step 3: Implement config and limits shape**

Change `src/data_agent_backend/config.py`.

```python
class BackendConfig(BaseModel):
    base_data_dir: Path = Field(default=Path(".data_agent"))
    sqlite_path: Path | None = None
    default_sql_row_limit: int = 1000
    max_sql_row_limit_without_approval: int = 10_000
    default_execution_timeout_ms: int = 300_000
    max_execution_timeout_ms: int = 600_000
    datasource_query_timeout_ms: int = 30_000
```

Change `src/data_agent_backend/models/execution.py`.

```python
class ExecutionLimits(BackendModel):
    timeout_ms: int | None = None
    row_limit: int | None = None
    memory_mb: int | None = None
```

- [ ] **Step 4: Implement effective timeout helper**

Add helpers near the top of `src/data_agent_backend/services/sandbox_executor.py`.

```python
def _timeout_seconds(timeout_ms: int) -> float:
    return timeout_ms / 1000


def _effective_timeout_ms(config: BackendConfig, limits: ExecutionLimits) -> int:
    timeout_ms = limits.timeout_ms if limits.timeout_ms is not None else config.default_execution_timeout_ms
    if timeout_ms <= 0:
        raise BackendError(
            "VALIDATION_ERROR",
            "Python execution timeout must be greater than 0.",
            {"timeout_ms": timeout_ms, "max_timeout_ms": config.max_execution_timeout_ms},
        )
    if timeout_ms > config.max_execution_timeout_ms:
        raise BackendError(
            "VALIDATION_ERROR",
            "Python execution timeout exceeds the configured maximum.",
            {"timeout_ms": timeout_ms, "max_timeout_ms": config.max_execution_timeout_ms},
        )
    return timeout_ms
```

Update local and docker executor call sites to compute `timeout_ms` before building the subprocess request.

```python
timeout_ms = _effective_timeout_ms(self.config, limits)
```

Then pass `timeout_ms=timeout_ms` to `_run_subprocess()` and `DockerSandboxRunRequest`.

- [ ] **Step 5: Run tests to verify pass**

Run:

```powershell
uv run pytest tests/test_sql_sandbox_mcp.py::test_python_execution_limits_default_to_configured_timeout tests/test_sql_sandbox_mcp.py::test_docker_sandbox_default_run_uses_configured_timeout -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```powershell
git add src/data_agent_backend/config.py src/data_agent_backend/models/execution.py src/data_agent_backend/services/sandbox_executor.py tests/test_sql_sandbox_mcp.py
git commit -m "Add Python sandbox timeout policy"
```

---

### Task 2: Timeout Validation And Explicit Override

**Files:**
- Modify: `tests/test_sql_sandbox_mcp.py`
- Modify: `src/data_agent_backend/services/sandbox_executor.py`

- [ ] **Step 1: Write failing tests for explicit timeout and validation**

Add these tests to `tests/test_sql_sandbox_mcp.py`.

```python
def test_docker_sandbox_explicit_timeout_overrides_config(services):
    class CapturingDockerProvider:
        def __init__(self):
            self.timeout_ms = None

        def run(self, request):
            self.timeout_ms = request.timeout_ms
            return DockerSandboxRunResult(exit_code=0, stdout="ok\n", stderr="", runtime_ms=12)

    provider = CapturingDockerProvider()
    executor = DockerSandboxExecutor(
        services.config,
        services.policy_engine,
        services.artifact_registry,
        services.artifact_store,
        provider=provider,
    )

    result = executor.run_python(
        "print('ok')",
        [],
        ExecutionLimits(timeout_ms=123_456),
        PolicyContext(run_id="run1", approval_id="approved"),
    )

    assert result.status == ExecutionStatus.success
    assert provider.timeout_ms == 123_456


def test_local_python_executor_rejects_non_positive_timeout(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        "print('bad timeout')",
        [],
        ExecutionLimits(timeout_ms=0),
        PolicyContext(run_id="run1"),
    )

    assert result.status == ExecutionStatus.error
    assert result.error_message == "VALIDATION_ERROR: Python execution timeout must be greater than 0."


def test_local_python_executor_rejects_timeout_above_max(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        "print('too long')",
        [],
        ExecutionLimits(timeout_ms=config.max_execution_timeout_ms + 1),
        PolicyContext(run_id="run1"),
    )

    assert result.status == ExecutionStatus.error
    assert result.error_message == "VALIDATION_ERROR: Python execution timeout exceeds the configured maximum."
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
uv run pytest tests/test_sql_sandbox_mcp.py::test_docker_sandbox_explicit_timeout_overrides_config tests/test_sql_sandbox_mcp.py::test_local_python_executor_rejects_non_positive_timeout tests/test_sql_sandbox_mcp.py::test_local_python_executor_rejects_timeout_above_max -q
```

Expected: validation tests FAIL until `BackendError` from timeout validation is converted into `ExecutionResult(status=error)`.

- [ ] **Step 3: Handle validation errors before subprocess execution**

In `LocalPythonSandboxExecutor.run_python()`, compute effective timeout inside the existing `try` block or add a small `try/except BackendError` before `_run_subprocess()`.

```python
try:
    timeout_ms = _effective_timeout_ms(self.config, limits)
except BackendError as exc:
    return ExecutionResult(
        execution_id=execution_id,
        status=ExecutionStatus.error,
        error_message=f"{exc.code}: {exc.message}",
    )
```

In `DockerSandboxExecutor.run_python()`, do the same before creating `DockerSandboxRunRequest`.

```python
try:
    timeout_ms = _effective_timeout_ms(self.config, limits)
except BackendError as exc:
    return ExecutionResult(
        execution_id=execution_id,
        status=ExecutionStatus.error,
        error_message=f"{exc.code}: {exc.message}",
    )
```

- [ ] **Step 4: Preserve timeout exception behavior**

Update `_run_subprocess()` and `DockerSandboxProvider.run()` to accept non-optional `timeout_ms: int` and pass seconds through `_timeout_seconds(timeout_ms)`.

```python
stdout, stderr = process.communicate(timeout=_timeout_seconds(timeout_ms))
```

```python
completed = subprocess.run(
    command,
    check=False,
    capture_output=True,
    text=True,
    timeout=_timeout_seconds(request.timeout_ms),
)
```

- [ ] **Step 5: Run tests to verify pass**

Run:

```powershell
uv run pytest tests/test_sql_sandbox_mcp.py::test_docker_sandbox_explicit_timeout_overrides_config tests/test_sql_sandbox_mcp.py::test_local_python_executor_rejects_non_positive_timeout tests/test_sql_sandbox_mcp.py::test_local_python_executor_rejects_timeout_above_max tests/test_sql_sandbox_mcp.py::test_local_python_executor_timeout -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add src/data_agent_backend/services/sandbox_executor.py tests/test_sql_sandbox_mcp.py
git commit -m "Validate Python sandbox timeout overrides"
```

---

### Task 3: Start And Finish Logs

**Files:**
- Modify: `tests/test_sql_sandbox_mcp.py`
- Modify: `src/data_agent_backend/services/sandbox_executor.py`

- [ ] **Step 1: Write failing tests for start and finish log files**

Add these tests to `tests/test_sql_sandbox_mcp.py`.

```python
def test_local_python_executor_writes_start_and_finish_logs(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        "print('logged')",
        [],
        ExecutionLimits(timeout_ms=5000),
        PolicyContext(run_id="run1"),
    )

    run_dir = config.sandbox_dir / "runs" / result.execution_id
    start_log = run_dir / "logs" / "execution_start.json"
    finish_log = run_dir / "logs" / "execution_finish.json"

    assert result.status == ExecutionStatus.success
    assert start_log.exists()
    assert finish_log.exists()
    start_data = json.loads(start_log.read_text(encoding="utf-8"))
    finish_data = json.loads(finish_log.read_text(encoding="utf-8"))
    assert start_data["execution_id"] == result.execution_id
    assert start_data["run_id"] == "run1"
    assert start_data["sandbox_backend"] == "local"
    assert start_data["timeout_ms"] == 5000
    assert start_data["status"] == "running"
    assert finish_data["execution_id"] == result.execution_id
    assert finish_data["status"] == "success"
    assert finish_data["exit_code"] == 0


def test_local_python_executor_writes_finish_log_on_timeout(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        "import time; time.sleep(2)",
        [],
        ExecutionLimits(timeout_ms=100),
        PolicyContext(run_id="run1"),
    )

    finish_log = config.sandbox_dir / "runs" / result.execution_id / "logs" / "execution_finish.json"
    finish_data = json.loads(finish_log.read_text(encoding="utf-8"))
    assert result.status == ExecutionStatus.timeout
    assert finish_data["status"] == "timeout"
    assert finish_data["error_message"] == "Python sandbox execution timed out."
```

Also add `import json` at the top of `tests/test_sql_sandbox_mcp.py` if missing.

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
uv run pytest tests/test_sql_sandbox_mcp.py::test_local_python_executor_writes_start_and_finish_logs tests/test_sql_sandbox_mcp.py::test_local_python_executor_writes_finish_log_on_timeout -q
```

Expected: FAIL because log files are not written.

- [ ] **Step 3: Add JSON log helpers**

Add helpers to `src/data_agent_backend/services/sandbox_executor.py`.

```python
def _write_json_file(path: Path, payload: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _write_start_log(
    paths: dict[str, Path],
    *,
    execution_id: str,
    run_id: str,
    sandbox_backend: str,
    timeout_ms: int,
    inputs: list[ArtifactRef],
) -> None:
    _write_json_file(
        paths["logs"] / "execution_start.json",
        {
            "execution_id": execution_id,
            "run_id": run_id,
            "sandbox_backend": sandbox_backend,
            "timeout_ms": timeout_ms,
            "input_artifact_ids": [item.artifact_id for item in inputs],
            "code_path": str((paths["code"] / "run.py").resolve()),
            "started_at": utc_now_iso(),
            "status": "running",
        },
    )


def _write_finish_log(
    paths: dict[str, Path],
    *,
    execution_id: str,
    status: ExecutionStatus,
    result: DockerSandboxRunResult,
    generated_artifact_ids: list[str],
) -> None:
    _write_json_file(
        paths["logs"] / "execution_finish.json",
        {
            "execution_id": execution_id,
            "status": status.value,
            "exit_code": result.exit_code,
            "runtime_ms": result.runtime_ms,
            "stdout": result.stdout[:4000],
            "stderr": result.stderr[:4000],
            "error_message": result.error_message,
            "finished_at": utc_now_iso(),
            "created_artifact_ids": generated_artifact_ids,
        },
    )
```

Import `utc_now_iso`.

```python
from data_agent_backend.models.common import BackendError, JsonDict, utc_now_iso
```

- [ ] **Step 4: Call log helpers in local and docker executors**

After `paths` and `timeout_ms` are ready, before subprocess/provider execution:

```python
_write_start_log(
    paths,
    execution_id=execution_id,
    run_id=run_id,
    sandbox_backend=self.sandbox_backend,
    timeout_ms=timeout_ms,
    inputs=inputs,
)
```

For `DockerSandboxExecutor`, use `sandbox_backend="docker"`.

After generated files and execution log artifact registration completes, write finish log:

```python
_write_finish_log(
    paths,
    execution_id=execution_id,
    status=status,
    result=result,
    generated_artifact_ids=generated_artifact_ids,
)
```

Place this call after any generated artifact IDs have been appended, so the finish log contains the final list.

- [ ] **Step 5: Run tests to verify pass**

Run:

```powershell
uv run pytest tests/test_sql_sandbox_mcp.py::test_local_python_executor_writes_start_and_finish_logs tests/test_sql_sandbox_mcp.py::test_local_python_executor_writes_finish_log_on_timeout -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```powershell
git add src/data_agent_backend/services/sandbox_executor.py tests/test_sql_sandbox_mcp.py
git commit -m "Record Python sandbox execution logs"
```

---

### Task 4: API And MCP Timeout Plumbing

**Files:**
- Modify: `tests/test_sql_sandbox_mcp.py`
- Modify: `tests/test_http_api.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `src/data_agent_backend/mcp/tools_execution.py`
- Modify: `src/data_agent_backend/api/routes_execution.py`

- [ ] **Step 1: Write failing MCP impl test**

Add to `tests/test_sql_sandbox_mcp.py`.

```python
def test_sandbox_run_python_impl_passes_timeout_to_executor(services):
    class CapturingSandboxExecutor:
        def __init__(self):
            self.limits = None

        def run_python(self, code, inputs, limits, context):
            self.limits = limits
            return services.sandbox_executor.run_python("print('ok')", [], ExecutionLimits(timeout_ms=5000), context)

    capturing = CapturingSandboxExecutor()
    services = services.__class__(**{**services.__dict__, "sandbox_executor": capturing})

    result = sandbox_run_python_impl(
        code="print('ok')",
        run_id="run1",
        timeout_ms=123_456,
        services=services,
    )

    assert result.ok is True
    assert capturing.limits.timeout_ms == 123_456
```

If `BackendServices` is a dataclass without `__dict__` compatibility, construct it with `dataclasses.replace(services, sandbox_executor=capturing)` and add `from dataclasses import replace`.

- [ ] **Step 2: Write failing public signature test**

Add to `tests/test_mcp_server.py`.

```python
def test_sandbox_run_python_public_signature_exposes_timeout_without_services():
    import inspect

    from data_agent_backend.mcp.tools_execution import sandbox_run_python

    signature = inspect.signature(sandbox_run_python)
    assert "timeout_ms" in signature.parameters
    assert "services" not in signature.parameters
```

- [ ] **Step 3: Write failing HTTP request model test**

Add to `tests/test_http_api.py`.

```python
def test_execution_python_accepts_timeout_ms(monkeypatch, services, client):
    captured = {}

    class CapturingExecutor:
        def run_python(self, code, inputs, limits, context):
            captured["timeout_ms"] = limits.timeout_ms
            return services.sandbox_executor.run_python("print('ok')", [], ExecutionLimits(timeout_ms=5000), context)

    monkeypatch.setattr(services, "sandbox_executor", CapturingExecutor())

    response = client.post(
        "/execution/python",
        json={"code": "print('ok')", "run_id": "run1", "timeout_ms": 123456},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["timeout_ms"] == 123456
```

Import `ExecutionLimits` if the file does not already import it.

- [ ] **Step 4: Run tests to verify failure**

Run:

```powershell
uv run pytest tests/test_sql_sandbox_mcp.py::test_sandbox_run_python_impl_passes_timeout_to_executor tests/test_mcp_server.py::test_sandbox_run_python_public_signature_exposes_timeout_without_services tests/test_http_api.py::test_execution_python_accepts_timeout_ms -q
```

Expected: FAIL because `timeout_ms` is not accepted or passed.

- [ ] **Step 5: Add timeout parameter to MCP wrapper**

Update `src/data_agent_backend/mcp/tools_execution.py`.

```python
def sandbox_run_python(
    code: str,
    run_id: str,
    input_artifact_ids: list[str] | None = None,
    timeout_ms: int | None = None,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    return sandbox_run_python_impl(
        code=code,
        run_id=run_id,
        input_artifact_ids=input_artifact_ids,
        timeout_ms=timeout_ms,
        context=context,
        services=get_services(),
    )
```

Update impl:

```python
def sandbox_run_python_impl(
    *,
    code: str,
    run_id: str,
    input_artifact_ids: list[str] | None = None,
    timeout_ms: int | None = None,
    context: dict[str, Any] | None = None,
    services: BackendServices,
) -> ToolResult:
    ctx = context_from(context, "sandbox_run_python")
    ctx = ctx.model_copy(update={"run_id": ctx.run_id or run_id})
    inputs = [ArtifactRef(artifact_id=item, type=ArtifactType.dataset) for item in (input_artifact_ids or [])]
    return result_wrap(lambda: services.sandbox_executor.run_python(code, inputs, ExecutionLimits(timeout_ms=timeout_ms), ctx))
```

- [ ] **Step 6: Add timeout to HTTP request model**

Update `src/data_agent_backend/api/routes_execution.py`.

```python
class PythonRunRequest(BackendModel):
    code: str
    run_id: str
    input_artifact_ids: list[str] | None = None
    timeout_ms: int | None = None
    context: ContextPayload = None
```

Pass it:

```python
sandbox_run_python_impl(
    code=payload.code,
    run_id=payload.run_id,
    input_artifact_ids=payload.input_artifact_ids,
    timeout_ms=payload.timeout_ms,
    context=payload.context,
    services=services,
)
```

- [ ] **Step 7: Run tests to verify pass**

Run:

```powershell
uv run pytest tests/test_sql_sandbox_mcp.py::test_sandbox_run_python_impl_passes_timeout_to_executor tests/test_mcp_server.py::test_sandbox_run_python_public_signature_exposes_timeout_without_services tests/test_http_api.py::test_execution_python_accepts_timeout_ms -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```powershell
git add src/data_agent_backend/mcp/tools_execution.py src/data_agent_backend/api/routes_execution.py tests/test_sql_sandbox_mcp.py tests/test_mcp_server.py tests/test_http_api.py
git commit -m "Expose Python sandbox timeout through API and MCP"
```

---

### Task 5: Agent Tool, Runtime, HTTP Agent, And CLI Timeout Plumbing

**Files:**
- Modify: `tests/test_agent_layer.py`
- Modify: `tests/test_http_api.py`
- Modify: `src/data_agent_agent/tools.py`
- Modify: `src/data_agent_agent/runtime.py`
- Modify: `src/data_agent_agent/runner.py`
- Modify: `src/data_agent_backend/api/routes_agent.py`

- [ ] **Step 1: Write failing agent tool test**

Update `test_run_python_injects_run_id_and_inputs` in `tests/test_agent_layer.py` so the invoke includes `timeout_ms`.

```python
result = await tools["run_python"].ainvoke(
    {"code": "print('ok')", "input_artifact_ids": ["art_1"], "timeout_ms": 123456}
)
```

Update the expected raw tool payload:

```python
{
    "code": "print('ok')",
    "run_id": "run_1",
    "input_artifact_ids": ["art_1"],
    "timeout_ms": 123456,
}
```

Add a new default timeout test.

```python
def test_run_python_uses_default_python_timeout_when_not_specified():
    async def scenario():
        calls = []
        raw_tools = {
            "datasource_get_catalog_summary": FakeRawTool("datasource_get_catalog_summary", {"ok": True, "data": {}, "error": None}, calls),
            "datasource_query": FakeRawTool("datasource_query", {"ok": True, "data": {}, "error": None}, calls),
            "sandbox_run_python": FakeRawTool("sandbox_run_python", {"ok": True, "data": {"status": "success"}, "error": None}, calls),
        }
        tools = {
            item.name: item
            for item in build_agent_tools(
                raw_tools,
                datasource_id="ds_1",
                run_id="run_1",
                default_python_timeout_ms=222_000,
            )
        }

        await tools["run_python"].ainvoke({"code": "print('ok')"})

        assert calls[-1][1]["timeout_ms"] == 222_000

    asyncio.run(scenario())
```

- [ ] **Step 2: Write failing runtime and CLI parser tests**

Add to `tests/test_agent_layer.py`.

```python
def test_parse_args_accepts_python_timeout_ms():
    args = parse_args(["--python-timeout-ms", "450000", "질문"])

    assert args.python_timeout_ms == 450000
    assert args.question == "질문"


def test_agent_runtime_passes_python_timeout_to_agent_tools():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        class CapturingRunner:
            async def run(self, *, question, model, tools, metadata):
                tool_names = [item.name for item in tools]
                events.append(("agent_run", {"tool_names": tool_names}))
                run_python = next(item for item in tools if item.name == "run_python")
                await run_python.ainvoke({"code": "print('ok')"})
                return {"answer": "완료", "raw_result": {"messages": []}}

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_runner=CapturingRunner(),
        )

        await runtime.run(
            AgentRunRequest(
                datasource_id="ds_1",
                question="질문",
                python_timeout_ms=333_000,
            )
        )

        python_call = next(event for event in events if event[0] == "sandbox_run_python")
        assert python_call[1]["timeout_ms"] == 333_000

    asyncio.run(scenario())
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_run_python_injects_run_id_and_inputs tests/test_agent_layer.py::test_run_python_uses_default_python_timeout_when_not_specified tests/test_agent_layer.py::test_parse_args_accepts_python_timeout_ms tests/test_agent_layer.py::test_agent_runtime_passes_python_timeout_to_agent_tools -q
```

Expected: FAIL because `timeout_ms`, `default_python_timeout_ms`, parser option, and `AgentRunRequest.python_timeout_ms` do not exist.

- [ ] **Step 4: Update agent tool wrapper**

Change `src/data_agent_agent/tools.py`.

```python
def build_agent_tools(
    raw_tools: dict[str, Any],
    *,
    datasource_id: str,
    run_id: str,
    default_row_limit: int = 1000,
    default_python_timeout_ms: int | None = None,
) -> list[BaseTool]:
```

Update `run_python`.

```python
@tool
async def run_python(
    code: str,
    input_artifact_ids: list[str] | None = None,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    """SQL 결과 artifact를 입력으로 받아 Python 후처리, 통계 계산, 시각화, 파일 생성을 실행한다."""
    effective_timeout_ms = timeout_ms if timeout_ms is not None else default_python_timeout_ms
    payload: dict[str, Any] = {
        "code": code,
        "run_id": run_id,
        "input_artifact_ids": input_artifact_ids or [],
    }
    if effective_timeout_ms is not None:
        payload["timeout_ms"] = effective_timeout_ms
    result = await call_raw_tool(raw_python, payload)
```

Keep the existing return shape after `result`.

- [ ] **Step 5: Update runtime request and build_agent_tools call**

Change `src/data_agent_agent/runtime.py`.

```python
@dataclass(frozen=True)
class AgentRunRequest:
    question: str
    datasource_id: str | None = None
    model: str | None = None
    row_limit: int | None = None
    python_timeout_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "data-agent-agent"
```

Pass it to tools:

```python
tools = build_agent_tools(
    raw_tools,
    datasource_id=resolved_datasource_id,
    run_id=run_id,
    default_row_limit=config.default_row_limit,
    default_python_timeout_ms=request.python_timeout_ms,
)
```

- [ ] **Step 6: Update CLI parser and run_cli**

Change `src/data_agent_agent/runner.py`.

```python
parser.add_argument("--python-timeout-ms", type=int, help="Python sandbox 기본 timeout(ms). 기본 300000, 최대 600000")
```

Update `run_cli()` signature:

```python
async def run_cli(
    *,
    datasource_id: str | None = None,
    question: str,
    model: str | None = None,
    row_limit: int | None = None,
    python_timeout_ms: int | None = None,
    config: AgentConfig | None = None,
    load_tools_func: LoadToolsFunc = load_backend_tools,
    agent_factory: AgentFactory = create_data_agent,
) -> AgentRunResult:
```

Pass it to `AgentRunRequest`.

```python
AgentRunRequest(
    datasource_id=datasource_id,
    question=question,
    model=model,
    row_limit=row_limit,
    python_timeout_ms=python_timeout_ms,
)
```

Pass parser value in `main()`.

```python
python_timeout_ms=args.python_timeout_ms,
```

- [ ] **Step 7: Add HTTP agent request field**

Change `src/data_agent_backend/api/routes_agent.py` request model and runtime call.

```python
class AgentAskRequest(BackendModel):
    question: str
    datasource_id: str | None = None
    model: str | None = None
    row_limit: int | None = None
    python_timeout_ms: int | None = None
    metadata: dict[str, Any] = {}
```

```python
AgentRunRequest(
    question=payload.question,
    datasource_id=payload.datasource_id,
    model=payload.model,
    row_limit=payload.row_limit,
    python_timeout_ms=payload.python_timeout_ms,
    metadata=payload.metadata,
    source="data-agent-api",
)
```

- [ ] **Step 8: Add HTTP agent test**

Add to `tests/test_http_api.py`.

```python
def test_agent_ask_accepts_python_timeout_ms(monkeypatch, services, client):
    captured = {}

    class FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, request):
            captured["python_timeout_ms"] = request.python_timeout_ms
            return AgentRunResult(answer="ok", run_id="run1", datasource_id="ds1", raw_result={})

    monkeypatch.setattr("data_agent_backend.api.routes_agent.AgentRuntime", FakeRuntime)

    response = client.post("/agent/ask", json={"question": "질문", "python_timeout_ms": 333000})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["python_timeout_ms"] == 333000
```

Import `AgentRunResult` if needed:

```python
from data_agent_agent.runtime import AgentRunResult
```

- [ ] **Step 9: Run tests to verify pass**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_run_python_injects_run_id_and_inputs tests/test_agent_layer.py::test_run_python_uses_default_python_timeout_when_not_specified tests/test_agent_layer.py::test_parse_args_accepts_python_timeout_ms tests/test_agent_layer.py::test_agent_runtime_passes_python_timeout_to_agent_tools tests/test_http_api.py::test_agent_ask_accepts_python_timeout_ms -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 5**

```powershell
git add src/data_agent_agent/tools.py src/data_agent_agent/runtime.py src/data_agent_agent/runner.py src/data_agent_backend/api/routes_agent.py tests/test_agent_layer.py tests/test_http_api.py
git commit -m "Pass Python sandbox timeout through agent runtime"
```

---

### Task 6: Agent Prompt Retry Rule

**Files:**
- Modify: `tests/test_agent_layer.py`
- Modify: `src/data_agent_agent/prompts/system.md`

- [ ] **Step 1: Write failing prompt rule test**

Add to `tests/test_agent_layer.py`.

```python
def test_system_prompt_includes_python_retry_rule():
    from data_agent_agent.deep_agent import load_system_prompt

    prompt = load_system_prompt()

    assert "run_python" in prompt
    assert "최대 1회" in prompt
    assert "status=timeout" in prompt
    assert "자동 재시도하지" in prompt
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_system_prompt_includes_python_retry_rule -q
```

Expected: FAIL because retry rule text is absent.

- [ ] **Step 3: Add retry rules to system prompt**

Append these Korean rules to `src/data_agent_agent/prompts/system.md` under the Python execution rules.

```markdown
18. `run_python` 결과가 `status=error`이면 `stderr`와 `error_message`를 읽고 원인을 수정한 뒤 최대 1회만 `run_python`을 다시 호출합니다.
19. `run_python` 결과가 `status=timeout`이면 같은 코드를 자동 재시도하지 않습니다. 입력 축소, 계산 단순화, 또는 명시적인 timeout 증가가 필요하다고 설명합니다.
20. Python 재시도 후에도 실패하면 실패 원인, 확인한 stderr/error_message, 다음 조치를 최종 답변에 포함합니다.
```

Keep the existing numbering consistent with nearby lines.

- [ ] **Step 4: Run test to verify pass**

Run:

```powershell
uv run pytest tests/test_agent_layer.py::test_system_prompt_includes_python_retry_rule -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

```powershell
git add src/data_agent_agent/prompts/system.md tests/test_agent_layer.py
git commit -m "Document Python retry behavior in agent prompt"
```

---

### Task 7: Analysis Optional Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add analysis extra to pyproject**

Change `[project.optional-dependencies]` in `pyproject.toml`.

```toml
[project.optional-dependencies]
dev = [
    "httpx>=0.27.0",
    "pytest>=8.0.0",
]
analysis = [
    "matplotlib>=3.8.0",
    "pandas>=2.2.0",
    "seaborn>=0.13.0",
]
```

- [ ] **Step 2: Validate dependency metadata**

Run:

```powershell
uv lock --check
```

Expected: If lockfile is stale, command reports it. Run `uv lock` to update `uv.lock`, then rerun `uv lock --check`.

- [ ] **Step 3: Install analysis extra in local environment**

Run:

```powershell
uv sync --extra dev --extra analysis
```

Expected: pandas, matplotlib, and seaborn install into the project environment.

- [ ] **Step 4: Verify imports**

Run:

```powershell
uv run python -c "import pandas, matplotlib, seaborn; print('analysis imports ok')"
```

Expected: prints `analysis imports ok`.

- [ ] **Step 5: Commit Task 7**

```powershell
git add pyproject.toml uv.lock
git commit -m "Add analysis dependencies for Python sandbox"
```

---

### Task 8: Full Verification

**Files:**
- No code changes unless verification reveals a failing test.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
uv run pytest tests/test_sql_sandbox_mcp.py tests/test_agent_layer.py tests/test_http_api.py tests/test_mcp_server.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
uv run pytest -q
```

Expected: all tests pass, with the existing optional MySQL integration skip if env is absent.

- [ ] **Step 3: Run diff check**

Run:

```powershell
git diff --check
```

Expected: exit code 0. CRLF warnings are acceptable if they match existing Git behavior; whitespace errors are not acceptable.

- [ ] **Step 4: Inspect final status**

Run:

```powershell
git status --short
```

Expected: only intentional files are modified. Existing unrelated `AGENTS.md` changes remain untouched.

- [ ] **Step 5: Final commit**

If individual task commits were not created, create one final implementation commit.

```powershell
git add src/data_agent_backend/config.py src/data_agent_backend/models/execution.py src/data_agent_backend/services/sandbox_executor.py src/data_agent_backend/mcp/tools_execution.py src/data_agent_backend/api/routes_execution.py src/data_agent_backend/api/routes_agent.py src/data_agent_agent/tools.py src/data_agent_agent/runtime.py src/data_agent_agent/runner.py src/data_agent_agent/prompts/system.md pyproject.toml uv.lock tests/test_sql_sandbox_mcp.py tests/test_agent_layer.py tests/test_http_api.py tests/test_mcp_server.py
git commit -m "Harden Python sandbox execution timeout"
```

Do not add `AGENTS.md` unless the user explicitly asks to include that existing change.

---

## Self-Review

- Spec coverage: 기본 5분/최대 10분 timeout은 Task 1과 Task 2가 구현한다. API/MCP/agent/CLI 전달은 Task 4와 Task 5가 구현한다. 시작/종료 로그는 Task 3이 구현한다. 프롬프트 기반 1회 재시도는 Task 6이 구현한다. `analysis` extra는 Task 7이 구현한다. 전체 검증은 Task 8이 담당한다.
- Exclusions: prelude 주입, 정적 검사, backend 코드 자동 수정, streaming 로그, background job/cancel API, SQL 성능 개선은 어느 task에도 포함하지 않았다.
- Type consistency: `timeout_ms`, `default_python_timeout_ms`, `python_timeout_ms`, `max_execution_timeout_ms` 이름을 전 task에서 동일하게 사용한다.
