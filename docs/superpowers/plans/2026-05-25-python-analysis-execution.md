# Python Analysis Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 에이전트가 로컬 개발 모드에서 승인 없이 Python 코드를 실행하고, SQL 결과 artifact를 후처리해 생성 파일을 artifact로 등록할 수 있게 만든다.

**Architecture:** `BackendConfig`가 `sandbox_backend=disabled|local|docker`를 선택하고, `factory.py`가 그 값에 따라 실행기를 조립한다. 새 `LocalPythonSandboxExecutor`는 기존 `SandboxExecutor` 계약을 구현하며, MCP/API의 `sandbox_run_python`과 agent의 `run_python` 도구는 backend 종류를 숨긴 공통 인터페이스를 유지한다.

**Tech Stack:** Python 3.11+, Pydantic, FastAPI, MCP tool wrapper, LangChain tools, pytest, subprocess, SQLite-backed artifact registry.

---

## Scope Check

이 계획은 단일 하위 시스템인 "Python 분석 실행 경로"만 다룬다. SQL 분석 품질, Docker 이미지 구성, 네트워크/패키지 설치 허용, notebook UI는 다루지 않는다.

## File Structure

- Modify: `src/data_agent_backend/config.py`
  - 환경 변수 기반 backend 설정을 읽고 `sandbox_backend`, `local_python_executable` 필드를 제공한다.
- Modify: `src/data_agent_backend/services/factory.py`
  - `sandbox_backend`에 따라 disabled, local, docker 실행기를 선택한다.
- Modify: `src/data_agent_backend/services/policy_engine.py`
  - `sandbox_backend="local"` payload일 때 `sandbox.python.run`을 승인 없이 허용한다.
- Modify: `src/data_agent_backend/services/sandbox_executor.py`
  - `LocalPythonSandboxExecutor`를 추가하고 Docker 실행기와 공유 가능한 작은 helper를 정리한다.
- Modify: `src/data_agent_backend/mcp/tools_execution.py`
  - 필요한 경우 Python 실행 ToolResult payload를 그대로 안정화한다.
- Modify: `src/data_agent_agent/mcp_client.py`
  - agent 필수 backend tool에 `sandbox_run_python`을 추가한다.
- Modify: `src/data_agent_agent/tool_provider.py`
  - in-process provider가 `sandbox_run_python_impl`을 노출한다.
- Modify: `src/data_agent_agent/tools.py`
  - agent용 `run_python` LangChain tool을 추가한다.
- Modify: `src/data_agent_agent/prompts/system.md`
  - SQL과 Python의 역할 분담, 입력/출력 경로 규칙을 안내한다.
- Modify: `.env.example`
  - 안전한 기본값 `DATA_AGENT_SANDBOX_BACKEND=disabled`를 문서화한다.
- Modify: `tests/test_sql_sandbox_mcp.py`
  - local executor, 정책, artifact 등록 테스트를 추가한다.
- Modify: `tests/test_http_api.py`
  - `/execution/python` local backend 성공 테스트를 추가한다.
- Modify: `tests/test_agent_layer.py`
  - agent tool 노출과 wrapper 동작 테스트를 추가한다.

---

### Task 1: Config And Factory Selection

**Files:**
- Modify: `src/data_agent_backend/config.py`
- Modify: `src/data_agent_backend/services/factory.py`
- Test: `tests/test_sql_sandbox_mcp.py`
- Test: `tests/conftest.py`

- [ ] **Step 1: Write failing tests for config env parsing and factory selection**

Append these tests to `tests/test_sql_sandbox_mcp.py`:

```python
def test_backend_config_reads_sandbox_backend_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_AGENT_SANDBOX_BACKEND", "local")
    monkeypatch.setenv("DATA_AGENT_LOCAL_PYTHON_EXECUTABLE", "python-custom")

    config = BackendConfig.from_env(base_data_dir=tmp_path / ".data_agent", load_env=False)

    assert config.sandbox_backend == "local"
    assert str(config.local_python_executable) == "python-custom"


def test_backend_config_rejects_unknown_sandbox_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_AGENT_SANDBOX_BACKEND", "unsafe")

    with pytest.raises(ValueError, match="DATA_AGENT_SANDBOX_BACKEND"):
        BackendConfig.from_env(base_data_dir=tmp_path / ".data_agent", load_env=False)


def test_factory_selects_local_python_executor(tmp_path):
    from data_agent_backend.services.sandbox_executor import LocalPythonSandboxExecutor

    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    assert isinstance(services.sandbox_executor, LocalPythonSandboxExecutor)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest -q tests/test_sql_sandbox_mcp.py::test_backend_config_reads_sandbox_backend_env tests/test_sql_sandbox_mcp.py::test_backend_config_rejects_unknown_sandbox_backend tests/test_sql_sandbox_mcp.py::test_factory_selects_local_python_executor
```

Expected: FAIL because `BackendConfig.from_env`, `sandbox_backend`, `local_python_executable`, and `LocalPythonSandboxExecutor` do not exist.

- [ ] **Step 3: Implement config fields and env parsing**

Modify `src/data_agent_backend/config.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field


SandboxBackend = Literal["disabled", "local", "docker"]


class BackendConfig(BaseModel):
    base_data_dir: Path = Field(default=Path(".data_agent"))
    sqlite_path: Path | None = None
    default_sql_row_limit: int = 1000
    max_sql_row_limit_without_approval: int = 10_000
    default_execution_timeout_ms: int = 30_000
    datasource_query_timeout_ms: int = 30_000
    datasource_max_result_bytes: int = 5_000_000
    datasource_max_cell_preview_chars: int = 1_000
    sandbox_backend: SandboxBackend = "disabled"
    local_python_executable: Path | None = None
    sandbox_enabled: bool = False
    sandbox_image: str = "python:3.11-slim"
    sandbox_memory: str = "512m"
    sandbox_cpus: float = 1.0
    sandbox_pids_limit: int = 128
    sandbox_tmpfs_size: str = "64m"
    sandbox_keep_run_dirs: bool = True
    network_enabled: bool = False
    package_install_policy: str = "blocked"
    artifact_id_strategy: str = "uuid4"

    @classmethod
    def from_env(
        cls,
        *,
        base_data_dir: Path | None = None,
        sqlite_path: Path | None = None,
        load_env: bool = True,
    ) -> "BackendConfig":
        if load_env:
            load_dotenv()
        sandbox_backend = os.getenv("DATA_AGENT_SANDBOX_BACKEND", "disabled").strip().lower() or "disabled"
        if sandbox_backend not in {"disabled", "local", "docker"}:
            raise ValueError("DATA_AGENT_SANDBOX_BACKEND must be one of: disabled, local, docker")
        local_python = os.getenv("DATA_AGENT_LOCAL_PYTHON_EXECUTABLE", "").strip()
        values = {
            "sandbox_backend": sandbox_backend,
            "local_python_executable": Path(local_python) if local_python else None,
        }
        if base_data_dir is not None:
            values["base_data_dir"] = base_data_dir
        if sqlite_path is not None:
            values["sqlite_path"] = sqlite_path
        return cls(**values)
```

Keep the existing properties and `ensure_dirs()` method below this block unchanged.

- [ ] **Step 4: Add a temporary LocalPythonSandboxExecutor shell**

Modify the import section and add this class near `DisabledSandboxExecutor` in `src/data_agent_backend/services/sandbox_executor.py`:

```python
class LocalPythonSandboxExecutor(DisabledSandboxExecutor):
    pass
```

This temporary shell only lets factory selection compile. Task 3 replaces it with the real implementation.

- [ ] **Step 5: Update factory selection**

Modify `src/data_agent_backend/services/factory.py` imports:

```python
from data_agent_backend.services.sandbox_executor import (
    DisabledSandboxExecutor,
    DockerSandboxExecutor,
    LocalPythonSandboxExecutor,
    SandboxExecutor,
)
```

Replace service config creation:

```python
def create_backend_services(config: BackendConfig | None = None) -> BackendServices:
    config = config or BackendConfig.from_env()
```

Replace sandbox executor selection:

```python
    if config.sandbox_backend == "local":
        sandbox_executor = LocalPythonSandboxExecutor(config, policy_engine, artifact_registry, artifact_store)
    elif config.sandbox_backend == "docker" or config.sandbox_enabled:
        sandbox_executor = DockerSandboxExecutor(config, policy_engine, artifact_registry, artifact_store)
    else:
        sandbox_executor = DisabledSandboxExecutor(policy_engine)
```

- [ ] **Step 6: Run tests to verify Task 1 passes**

Run:

```powershell
uv run pytest -q tests/test_sql_sandbox_mcp.py::test_backend_config_reads_sandbox_backend_env tests/test_sql_sandbox_mcp.py::test_backend_config_rejects_unknown_sandbox_backend tests/test_sql_sandbox_mcp.py::test_factory_selects_local_python_executor
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```powershell
git add src/data_agent_backend/config.py src/data_agent_backend/services/factory.py src/data_agent_backend/services/sandbox_executor.py tests/test_sql_sandbox_mcp.py
git commit -m "Add sandbox backend configuration"
```

---

### Task 2: Local Policy Approval Bypass

**Files:**
- Modify: `src/data_agent_backend/services/policy_engine.py`
- Modify: `src/data_agent_backend/services/sandbox_executor.py`
- Test: `tests/test_sql_sandbox_mcp.py`

- [ ] **Step 1: Write failing policy tests**

Append to `tests/test_sql_sandbox_mcp.py`:

```python
def test_policy_allows_local_python_without_approval(services):
    decision = services.policy_engine.evaluate(
        "sandbox.python.run",
        "python",
        {"sandbox_backend": "local", "code_bytes": 12, "input_artifact_ids": []},
        PolicyContext(run_id="run1"),
    )

    assert decision.allowed is True
    assert decision.requires_approval is False


def test_policy_still_requires_approval_for_docker_python(services):
    decision = services.policy_engine.evaluate(
        "sandbox.python.run",
        "python",
        {"sandbox_backend": "docker", "code_bytes": 12, "input_artifact_ids": []},
        PolicyContext(run_id="run1"),
    )

    assert decision.allowed is False
    assert decision.requires_approval is True
```

- [ ] **Step 2: Run tests to verify first test fails**

Run:

```powershell
uv run pytest -q tests/test_sql_sandbox_mcp.py::test_policy_allows_local_python_without_approval tests/test_sql_sandbox_mcp.py::test_policy_still_requires_approval_for_docker_python
```

Expected: FAIL on local policy because `sandbox.python.run` currently always requires approval without `approval_id`.

- [ ] **Step 3: Implement local policy rule**

Modify the `sandbox.python.run` block in `src/data_agent_backend/services/policy_engine.py`:

```python
        if action in {"sandbox.python.run", "export.create"}:
            if action == "sandbox.python.run" and payload.get("sandbox_backend") == "local":
                return self._decision(True, False, RiskLevel.medium, "Local development Python execution is allowed.")
            if context.approval_id:
                return self._decision(True, False, RiskLevel.medium, "Approved operation may proceed.")
            return self._decision(False, True, RiskLevel.high, f"{action} requires approval.", ["payload"])
```

- [ ] **Step 4: Update local executor policy payload**

When Task 3 replaces the temporary shell, its policy payload must include:

```python
{
    "sandbox_backend": "local",
    "code_bytes": len(code.encode("utf-8")),
    "input_artifact_ids": [item.artifact_id for item in inputs],
}
```

For this task, no additional code is required if the temporary shell is still present.

- [ ] **Step 5: Run policy tests**

Run:

```powershell
uv run pytest -q tests/test_sql_sandbox_mcp.py::test_policy_allows_local_python_without_approval tests/test_sql_sandbox_mcp.py::test_policy_still_requires_approval_for_docker_python
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add src/data_agent_backend/services/policy_engine.py tests/test_sql_sandbox_mcp.py
git commit -m "Allow local Python execution policy"
```

---

### Task 3: Local Python Sandbox Executor

**Files:**
- Modify: `src/data_agent_backend/services/sandbox_executor.py`
- Test: `tests/test_sql_sandbox_mcp.py`

- [ ] **Step 1: Write failing tests for local execution**

Append to `tests/test_sql_sandbox_mcp.py`:

```python
def test_local_python_executor_runs_without_approval_and_registers_outputs(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        """
import os
from pathlib import Path

outputs = Path(os.environ["DATA_AGENT_OUTPUTS_DIR"])
workspace = Path(os.environ["DATA_AGENT_WORKSPACE_DIR"])
outputs.joinpath("result.csv").write_text("x\\n1\\n", encoding="utf-8")
workspace.joinpath("report.md").write_text("# Report\\ncreated", encoding="utf-8")
print("hello from local python")
""",
        [],
        ExecutionLimits(timeout_ms=5000),
        PolicyContext(run_id="run1"),
    )

    assert result.status == ExecutionStatus.success
    assert result.exit_code == 0
    assert "hello from local python" in result.stdout
    records = [services.artifact_registry.get_artifact(artifact_id) for artifact_id in result.created_artifact_ids]
    generated = [record for record in records if record.type.value != "execution_log"]
    assert {record.metadata["sandbox_relative_path"] for record in generated} == {"report.md", "result.csv"}
    assert {record.metadata["sandbox_backend"] for record in generated} == {"local"}
    assert any(record.type.value == "execution_log" for record in records)


def test_local_python_executor_can_read_input_artifact(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)
    input_record = services.artifact_registry.register_artifact(
        ArtifactRegisterRequest(
            run_id="run1",
            type=ArtifactType.dataset,
            content_text="value\\n41\\n",
            filename="input.csv",
            created_by_tool="test",
        ),
        PolicyContext(run_id="run1"),
    )

    result = services.sandbox_executor.run_python(
        """
import os
from pathlib import Path

inputs = Path(os.environ["DATA_AGENT_INPUTS_DIR"])
outputs = Path(os.environ["DATA_AGENT_OUTPUTS_DIR"])
source = next(inputs.rglob("input.csv"))
value = source.read_text(encoding="utf-8").splitlines()[1]
outputs.joinpath("derived.txt").write_text(f"value={value}", encoding="utf-8")
""",
        [input_record.ref()],
        ExecutionLimits(timeout_ms=5000),
        PolicyContext(run_id="run1"),
    )

    assert result.status == ExecutionStatus.success
    derived = [services.artifact_registry.get_artifact(item) for item in result.created_artifact_ids if item != input_record.artifact_id]
    text_records = [record for record in derived if record.metadata.get("sandbox_relative_path") == "derived.txt"]
    assert len(text_records) == 1
    lineage = services.artifact_registry.get_lineage(text_records[0].artifact_id)
    assert lineage[0]["parent_id"] == input_record.artifact_id
    assert lineage[0]["edge_type"] == "generated_by_python"


def test_local_python_executor_timeout(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        "import time; time.sleep(2)",
        [],
        ExecutionLimits(timeout_ms=100),
        PolicyContext(run_id="run1"),
    )

    assert result.status == ExecutionStatus.timeout
    assert result.error_message == "Python sandbox execution timed out."
```

Add imports at the top of `tests/test_sql_sandbox_mcp.py`:

```python
from data_agent_backend.models.artifacts import ArtifactRegisterRequest, ArtifactType
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest -q tests/test_sql_sandbox_mcp.py::test_local_python_executor_runs_without_approval_and_registers_outputs tests/test_sql_sandbox_mcp.py::test_local_python_executor_can_read_input_artifact tests/test_sql_sandbox_mcp.py::test_local_python_executor_timeout
```

Expected: FAIL because `LocalPythonSandboxExecutor` still inherits disabled behavior.

- [ ] **Step 3: Add subprocess imports**

Modify `src/data_agent_backend/services/sandbox_executor.py` imports:

```python
import os
import sys
```

The file already imports `json`, `shutil`, `subprocess`, `time`, `dataclass`, `Path`, and `Protocol`.

- [ ] **Step 4: Replace the temporary LocalPythonSandboxExecutor**

Replace the temporary shell class with:

```python
class LocalPythonSandboxExecutor:
    def __init__(
        self,
        config: BackendConfig,
        policy_engine: PolicyEngine,
        artifact_registry: ArtifactRegistry,
        artifact_store: ArtifactStore,
        id_generator: UUID4IdGenerator | None = None,
    ) -> None:
        self.config = config
        self.policy_engine = policy_engine
        self.artifact_registry = artifact_registry
        self.artifact_store = artifact_store
        self.id_generator = id_generator or UUID4IdGenerator()

    def run_python(
        self,
        code: str,
        inputs: list[ArtifactRef],
        limits: ExecutionLimits,
        context: PolicyContext,
    ) -> ExecutionResult:
        execution_id = self.id_generator.new_id("exec")
        decision = self.policy_engine.evaluate(
            "sandbox.python.run",
            "python",
            {
                "sandbox_backend": "local",
                "code_bytes": len(code.encode("utf-8")),
                "input_artifact_ids": [item.artifact_id for item in inputs],
            },
            context,
        )
        if decision.requires_approval:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.approval_required,
                approval_id=context.approval_id,
                error_message=decision.reason,
            )
        if not decision.allowed:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.policy_blocked,
                error_message=decision.reason,
            )

        run_id = context.run_id or execution_id
        run_dir = ensure_child_path(self.config.sandbox_dir, self.config.sandbox_dir / "runs" / execution_id)
        paths = self._prepare_run_dir(run_dir, code, inputs)
        before = self._snapshot(paths["workspace"], paths["outputs"])
        result = self._run_subprocess(paths, limits)
        generated_artifact_ids: list[str] = []
        status = self._status_from_run_result(result)
        error_message = result.error_message

        try:
            generated_artifact_ids.extend(self._register_generated_files(run_id, execution_id, paths, before, inputs, context))
            log_artifact = self._register_execution_log(run_id, execution_id, status, result, generated_artifact_ids, inputs, context)
            generated_artifact_ids.append(log_artifact.artifact_id)
        except BackendError as exc:
            status = ExecutionStatus.error
            error_message = f"{exc.code}: {exc.message}"

        if not self.config.sandbox_keep_run_dirs:
            shutil.rmtree(run_dir, ignore_errors=True)

        return ExecutionResult(
            execution_id=execution_id,
            status=status,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            runtime_ms=result.runtime_ms,
            created_artifact_ids=generated_artifact_ids,
            error_message=error_message,
        )
```

- [ ] **Step 5: Add local helper methods**

Add these methods inside `LocalPythonSandboxExecutor`:

```python
    def _prepare_run_dir(self, run_dir: Path, code: str, inputs: list[ArtifactRef]) -> dict[str, Path]:
        paths = {
            "code": ensure_child_path(run_dir, run_dir / "code"),
            "inputs": ensure_child_path(run_dir, run_dir / "inputs"),
            "workspace": ensure_child_path(run_dir, run_dir / "workspace"),
            "outputs": ensure_child_path(run_dir, run_dir / "outputs"),
            "logs": ensure_child_path(run_dir, run_dir / "logs"),
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        ensure_child_path(paths["code"], paths["code"] / "run.py").write_text(code, encoding="utf-8")
        for item in inputs:
            source = self.artifact_store.get_path(item.artifact_id)
            input_dir = ensure_child_path(paths["inputs"], paths["inputs"] / safe_filename(item.artifact_id))
            input_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, ensure_child_path(input_dir, input_dir / safe_filename(source.name)))
        return paths

    def _run_subprocess(self, paths: dict[str, Path], limits: ExecutionLimits) -> DockerSandboxRunResult:
        executable = str(self.config.local_python_executable or sys.executable)
        env = {
            **os.environ,
            "DATA_AGENT_INPUTS_DIR": str(paths["inputs"].resolve()),
            "DATA_AGENT_WORKSPACE_DIR": str(paths["workspace"].resolve()),
            "DATA_AGENT_OUTPUTS_DIR": str(paths["outputs"].resolve()),
            "DATA_AGENT_EXECUTION_ID": paths["code"].parent.name,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [executable, str((paths["code"] / "run.py").resolve())],
                check=False,
                capture_output=True,
                text=True,
                cwd=paths["workspace"],
                env=env,
                timeout=(limits.timeout_ms or self.config.default_execution_timeout_ms) / 1000,
            )
            return DockerSandboxRunResult(
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                runtime_ms=int((time.monotonic() - started) * 1000),
            )
        except subprocess.TimeoutExpired as exc:
            return DockerSandboxRunResult(
                exit_code=None,
                stdout=_decode_output(exc.stdout),
                stderr=_decode_output(exc.stderr),
                runtime_ms=int((time.monotonic() - started) * 1000),
                timed_out=True,
                error_message="Python sandbox execution timed out.",
            )
        except FileNotFoundError:
            return DockerSandboxRunResult(
                exit_code=None,
                stdout="",
                stderr="",
                runtime_ms=int((time.monotonic() - started) * 1000),
                error_message="Python executable was not found.",
            )
```

- [ ] **Step 6: Add artifact helper methods**

Still inside `LocalPythonSandboxExecutor`, add methods equivalent to Docker with local metadata:

```python
    def _snapshot(self, *roots: Path) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for root in roots:
            for path in self._iter_files(root):
                stat = path.stat()
                snapshot[self._snapshot_key(root, path)] = (stat.st_size, stat.st_mtime_ns)
        return snapshot

    def _register_generated_files(
        self,
        run_id: str,
        execution_id: str,
        paths: dict[str, Path],
        before: dict[str, tuple[int, int]],
        inputs: list[ArtifactRef],
        context: PolicyContext,
    ) -> list[str]:
        artifact_ids: list[str] = []
        for root_name in ("workspace", "outputs"):
            root = paths[root_name]
            for path in self._iter_files(root):
                stat = path.stat()
                key = self._snapshot_key(root, path)
                if before.get(key) == (stat.st_size, stat.st_mtime_ns):
                    continue
                relative_path = path.relative_to(root).as_posix()
                record = self.artifact_registry.register_artifact(
                    ArtifactRegisterRequest(
                        run_id=run_id,
                        type=self._artifact_type_for_path(path),
                        content_bytes=path.read_bytes(),
                        filename=path.name,
                        thread_id=context.thread_id,
                        project_id=context.project_id,
                        created_by_tool="sandbox_run_python",
                        parent_ids=[item.artifact_id for item in inputs],
                        lineage_edge_type="generated_by_python",
                        metadata={
                            "execution_id": execution_id,
                            "sandbox_backend": "local",
                            "sandbox_root": root_name,
                            "sandbox_relative_path": relative_path,
                            "format": path.suffix.removeprefix(".") or "binary",
                        },
                        approval_id=context.approval_id,
                    ),
                    context,
                )
                artifact_ids.append(record.artifact_id)
        return artifact_ids

    def _register_execution_log(
        self,
        run_id: str,
        execution_id: str,
        status: ExecutionStatus,
        result: DockerSandboxRunResult,
        generated_artifact_ids: list[str],
        inputs: list[ArtifactRef],
        context: PolicyContext,
    ):
        log: JsonDict = {
            "execution_id": execution_id,
            "sandbox_backend": "local",
            "status": status.value,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "runtime_ms": result.runtime_ms,
            "artifacts": generated_artifact_ids,
            "timed_out": result.timed_out,
            "error_message": result.error_message,
        }
        return self.artifact_registry.register_artifact(
            ArtifactRegisterRequest(
                run_id=run_id,
                type=ArtifactType.execution_log,
                content_text=json.dumps(log, ensure_ascii=False, sort_keys=True),
                filename="execution_log.json",
                thread_id=context.thread_id,
                project_id=context.project_id,
                created_by_tool="sandbox_run_python",
                parent_ids=[item.artifact_id for item in inputs],
                lineage_edge_type="execution_log_for",
                metadata={
                    "execution_id": execution_id,
                    "sandbox_backend": "local",
                    "status": status.value,
                    "exit_code": result.exit_code,
                    "runtime_ms": result.runtime_ms,
                },
                preview={
                    "status": status.value,
                    "stdout_snippet": result.stdout[:1000],
                    "stderr_snippet": result.stderr[:1000],
                    "exit_code": result.exit_code,
                    "runtime_ms": result.runtime_ms,
                },
                approval_id=context.approval_id,
            ),
            context,
        )

    def _iter_files(self, root: Path) -> list[Path]:
        if not root.exists():
            return []
        return sorted((path for path in root.rglob("*") if path.is_file()), key=lambda item: item.relative_to(root).as_posix())

    def _snapshot_key(self, root: Path, path: Path) -> str:
        return f"{root.name}/{path.relative_to(root).as_posix()}"

    def _artifact_type_for_path(self, path: Path) -> ArtifactType:
        suffix = path.suffix.lower()
        if suffix in {".csv", ".tsv", ".json", ".jsonl", ".parquet"}:
            return ArtifactType.dataset
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}:
            return ArtifactType.chart
        if suffix in {".md", ".markdown", ".txt", ".html"}:
            return ArtifactType.report
        return ArtifactType.file

    def _status_from_run_result(self, result: DockerSandboxRunResult) -> ExecutionStatus:
        if result.timed_out:
            return ExecutionStatus.timeout
        if result.error_message:
            return ExecutionStatus.error
        if result.exit_code == 0:
            return ExecutionStatus.success
        return ExecutionStatus.error
```

- [ ] **Step 7: Run local executor tests**

Run:

```powershell
uv run pytest -q tests/test_sql_sandbox_mcp.py::test_local_python_executor_runs_without_approval_and_registers_outputs tests/test_sql_sandbox_mcp.py::test_local_python_executor_can_read_input_artifact tests/test_sql_sandbox_mcp.py::test_local_python_executor_timeout
```

Expected: PASS.

- [ ] **Step 8: Run existing sandbox tests**

Run:

```powershell
uv run pytest -q tests/test_sql_sandbox_mcp.py
```

Expected: PASS, including disabled and Docker fake-provider tests.

- [ ] **Step 9: Commit Task 3**

```powershell
git add src/data_agent_backend/services/sandbox_executor.py tests/test_sql_sandbox_mcp.py
git commit -m "Add local Python sandbox executor"
```

---

### Task 4: MCP And HTTP Python Execution

**Files:**
- Modify: `tests/test_http_api.py`
- Review: `src/data_agent_backend/mcp/tools_execution.py`
- Review: `src/data_agent_backend/api/routes_execution.py`

- [ ] **Step 1: Write HTTP local execution test**

Append to `tests/test_http_api.py`:

```python
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
```

- [ ] **Step 2: Run HTTP tests**

Run:

```powershell
uv run pytest -q tests/test_http_api.py::test_execution_python_endpoint_keeps_disabled_contract tests/test_http_api.py::test_execution_python_endpoint_runs_local_backend
```

Expected: PASS if Task 3 is complete. If it fails because Pydantic serialization cannot handle `ExecutionStatus`, inspect `ToolResult` serialization and convert via existing `model_dump(mode="json")` path.

- [ ] **Step 3: Confirm MCP wrapper contract**

Run:

```powershell
uv run pytest -q tests/test_sql_sandbox_mcp.py::test_mcp_tools_return_tool_result_envelope tests/test_mcp_server.py::test_create_mcp_server_registers_tools
```

Expected: PASS. If the exact `test_mcp_server.py` test name differs, run `uv run pytest -q tests/test_mcp_server.py`.

- [ ] **Step 4: Commit Task 4**

```powershell
git add tests/test_http_api.py
git commit -m "Cover local Python execution API"
```

---

### Task 5: Agent Tool Exposure

**Files:**
- Modify: `src/data_agent_agent/mcp_client.py`
- Modify: `src/data_agent_agent/tool_provider.py`
- Modify: `src/data_agent_agent/tools.py`
- Test: `tests/test_agent_layer.py`

- [ ] **Step 1: Write failing agent tool tests**

Update `make_raw_tools()` in `tests/test_agent_layer.py` so the default raw tool set includes:

```python
        "sandbox_run_python": FakeRawTool(
            "sandbox_run_python",
            {
                "ok": True,
                "data": {
                    "execution_id": "exec_1",
                    "status": "success",
                    "exit_code": 0,
                    "stdout": "done\\n",
                    "stderr": "",
                    "runtime_ms": 10,
                    "created_artifact_ids": ["art_chart", "art_log"],
                    "error_message": None,
                },
                "error": None,
            },
            events,
        ),
```

Append tests:

```python
def test_run_python_injects_run_id_and_inputs():
    async def scenario():
        calls = []
        raw_tools = {
            "datasource_get_catalog_summary": FakeRawTool("datasource_get_catalog_summary", {"ok": True, "data": {}, "error": None}, calls),
            "datasource_query": FakeRawTool("datasource_query", {"ok": True, "data": {}, "error": None}, calls),
            "sandbox_run_python": FakeRawTool(
                "sandbox_run_python",
                {
                    "ok": True,
                    "data": {
                        "execution_id": "exec_1",
                        "status": "success",
                        "exit_code": 0,
                        "stdout": "ok\\n",
                        "stderr": "",
                        "runtime_ms": 7,
                        "created_artifact_ids": ["art_2"],
                        "error_message": None,
                    },
                    "error": None,
                },
                calls,
            ),
        }
        tools = {item.name: item for item in build_agent_tools(raw_tools, datasource_id="ds_1", run_id="run_1")}

        result = await tools["run_python"].ainvoke({"code": "print('ok')", "input_artifact_ids": ["art_1"]})

        assert result["status"] == "success"
        assert result["created_artifact_ids"] == ["art_2"]
        assert calls == [
            (
                "sandbox_run_python",
                {
                    "code": "print('ok')",
                    "run_id": "run_1",
                    "input_artifact_ids": ["art_1"],
                },
            )
        ]

    asyncio.run(scenario())


def test_run_python_preserves_backend_error_details():
    async def scenario():
        calls = []
        raw_tools = {
            "datasource_get_catalog_summary": FakeRawTool("datasource_get_catalog_summary", {"ok": True, "data": {}, "error": None}, calls),
            "datasource_query": FakeRawTool("datasource_query", {"ok": True, "data": {}, "error": None}, calls),
            "sandbox_run_python": FakeRawTool(
                "sandbox_run_python",
                {
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "POLICY_BLOCKED",
                        "message": "Blocked.",
                        "details": {"decision_id": "pd_1"},
                    },
                },
                calls,
            ),
        }
        tools = {item.name: item for item in build_agent_tools(raw_tools, datasource_id="ds_1", run_id="run_1")}

        result = await tools["run_python"].ainvoke({"code": "print('blocked')"})

        assert result["ok"] is False
        assert result["code"] == "POLICY_BLOCKED"
        assert result["message"] == "Blocked."
        assert result["details"] == {"decision_id": "pd_1"}

    asyncio.run(scenario())
```

Update `test_agent_runtime_uses_agent_runner_adapter` assertion:

```python
        assert "run_python" in events[1][1]["tool_names"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest -q tests/test_agent_layer.py::test_run_python_injects_run_id_and_inputs tests/test_agent_layer.py::test_run_python_preserves_backend_error_details tests/test_agent_layer.py::test_agent_runtime_uses_agent_runner_adapter
```

Expected: FAIL because `run_python` is not exposed.

- [ ] **Step 3: Add required MCP tool**

Modify `src/data_agent_agent/mcp_client.py`:

```python
REQUIRED_BACKEND_TOOLS = {
    "run_create",
    "datasource_list",
    "datasource_create",
    "datasource_test",
    "datasource_refresh_catalog",
    "datasource_get_catalog_summary",
    "analysis_build_context",
    "datasource_query",
    "sandbox_run_python",
}
```

- [ ] **Step 4: Add in-process raw tool**

Modify `src/data_agent_agent/tool_provider.py` imports:

```python
from data_agent_backend.mcp.tools_execution import sandbox_run_python_impl
```

Add to `InProcessBackendToolProvider.load_tools()` map:

```python
            "sandbox_run_python": sandbox_run_python_impl,
```

- [ ] **Step 5: Add run_python LangChain tool**

Modify `src/data_agent_agent/tools.py` inside `build_agent_tools()`:

```python
    raw_python = raw_tools["sandbox_run_python"]
```

Add this tool before `return agent_tools`:

```python
    @tool
    async def run_python(code: str, input_artifact_ids: list[str] | None = None) -> dict[str, Any]:
        """SQL 결과 artifact를 입력으로 받아 Python 후처리, 통계 계산, 시각화, 파일 생성을 실행한다."""
        result = await call_raw_tool(
            raw_python,
            {
                "code": code,
                "run_id": run_id,
                "input_artifact_ids": input_artifact_ids or [],
            },
        )
        if not result.get("ok"):
            return error_payload(result)
        data = result.get("data") or {}
        return {
            "execution_id": data.get("execution_id"),
            "status": data.get("status"),
            "exit_code": data.get("exit_code"),
            "stdout": data.get("stdout", ""),
            "stderr": data.get("stderr", ""),
            "runtime_ms": data.get("runtime_ms", 0),
            "created_artifact_ids": data.get("created_artifact_ids", []),
            "error_message": data.get("error_message"),
        }

    agent_tools.append(run_python)
```

- [ ] **Step 6: Run agent layer tests**

Run:

```powershell
uv run pytest -q tests/test_agent_layer.py::test_run_python_injects_run_id_and_inputs tests/test_agent_layer.py::test_run_python_preserves_backend_error_details tests/test_agent_layer.py::test_agent_runtime_uses_agent_runner_adapter tests/test_agent_layer.py::test_in_process_backend_tool_provider_exposes_required_tools
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```powershell
git add src/data_agent_agent/mcp_client.py src/data_agent_agent/tool_provider.py src/data_agent_agent/tools.py tests/test_agent_layer.py
git commit -m "Expose Python execution to agent"
```

---

### Task 6: Prompt And Env Example

**Files:**
- Modify: `src/data_agent_agent/prompts/system.md`
- Modify: `.env.example`

- [ ] **Step 1: Update env example**

Append to `.env.example`:

```dotenv

# Python execution backend. Keep disabled by default; use local for development analysis runs.
DATA_AGENT_SANDBOX_BACKEND=disabled
DATA_AGENT_LOCAL_PYTHON_EXECUTABLE=
```

- [ ] **Step 2: Update system prompt**

Append this Korean guidance to `src/data_agent_agent/prompts/system.md`:

```markdown

Python 실행 규칙:

11. SQL은 datasource에서 원자료를 추출하거나 DB 집계를 수행할 때 사용합니다.
12. SQL 결과를 후처리하거나, 통계 계산을 반복하거나, 차트/CSV/JSON/HTML/Markdown 파일을 만들어야 하면 `run_python`을 사용합니다.
13. `run_sql`이 반환한 `artifact_ref.artifact_id`를 `run_python`의 `input_artifact_ids`에 전달합니다.
14. Python 코드에서 입력 파일은 `DATA_AGENT_INPUTS_DIR` 아래에서 찾습니다.
15. Python 코드가 생성하는 파일은 `DATA_AGENT_OUTPUTS_DIR` 아래에 저장합니다.
16. 네트워크 호출이나 패키지 설치는 시도하지 않습니다.
17. 최종 답변에는 Python이 만든 주요 artifact id와 그 파일의 의미를 간단히 설명합니다.
```

- [ ] **Step 3: Run prompt/env smoke tests**

Run:

```powershell
uv run pytest -q tests/test_agent_layer.py::test_agent_layer_import_smoke
```

Expected: PASS.

- [ ] **Step 4: Commit Task 6**

```powershell
git add .env.example src/data_agent_agent/prompts/system.md
git commit -m "Document Python analysis tool usage"
```

---

### Task 7: End-To-End Verification

**Files:**
- Verify: all files touched above

- [ ] **Step 1: Run targeted backend and agent tests**

Run:

```powershell
uv run pytest -q tests/test_sql_sandbox_mcp.py tests/test_http_api.py tests/test_agent_layer.py
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
uv run pytest -q
```

Expected: PASS. If this command exceeds the local time budget, capture the timeout and run the targeted tests from Step 1 as the verified subset.

- [ ] **Step 3: Run manual local Python smoke through backend services**

Run:

```powershell
$env:DATA_AGENT_SANDBOX_BACKEND='local'
@'
from data_agent_backend.services import create_backend_services
from data_agent_backend.mcp.tools_execution import sandbox_run_python_impl

services = create_backend_services()
result = sandbox_run_python_impl(
    code="import os; from pathlib import Path; Path(os.environ['DATA_AGENT_OUTPUTS_DIR']).joinpath('smoke.txt').write_text('ok', encoding='utf-8'); print('smoke-ok')",
    run_id="run_smoke",
    services=services,
)
print(result.model_dump(mode="json"))
'@ | uv run python -
```

Expected: printed ToolResult has `ok=True`, `data.status='success'`, stdout containing `smoke-ok`, and at least two `created_artifact_ids` for `smoke.txt` and `execution_log.json`.

- [ ] **Step 4: Run manual in-process agent tool smoke**

Run:

```powershell
$env:DATA_AGENT_SANDBOX_BACKEND='local'
@'
import asyncio

from data_agent_agent.config import AgentConfig
from data_agent_agent.tool_provider import InProcessBackendToolProvider
from data_agent_agent.tools import build_agent_tools
from data_agent_backend.services import create_backend_services


async def main():
    services = create_backend_services()
    raw_tools = await InProcessBackendToolProvider(services).load_tools(AgentConfig(openai_api_key="test-key"))
    tools = {tool.name: tool for tool in build_agent_tools(raw_tools, datasource_id="ds_1", run_id="run_agent_smoke")}
    result = await tools["run_python"].ainvoke(
        {
            "code": "import os; from pathlib import Path; Path(os.environ['DATA_AGENT_OUTPUTS_DIR']).joinpath('agent-smoke.txt').write_text('ok', encoding='utf-8'); print('agent-smoke-ok')"
        }
    )
    print(result)


asyncio.run(main())
'@ | uv run python -
```

Expected: output dictionary has `status='success'`, stdout containing `agent-smoke-ok`, and non-empty `created_artifact_ids`.

- [ ] **Step 5: Check git status**

Run:

```powershell
git status --short
```

Expected: no unstaged changes except intentional files if a previous commit step was skipped.

- [ ] **Step 6: Final commit for verification adjustments**

If verification required small fixes, commit them:

```powershell
git add src tests .env.example
git commit -m "Verify Python analysis execution"
```

If there are no changes after Step 5, skip this commit.

---

## Self-Review

- Spec coverage: configuration, local executor, policy approval bypass, MCP/API continuity, agent tool exposure, prompt guidance, artifact registration, lineage, and tests are covered by Tasks 1 through 7.
- Placeholder scan: the plan contains concrete commands, code snippets, expected failures, expected passes, and commit commands for each task.
- Type consistency: `sandbox_backend`, `local_python_executable`, `LocalPythonSandboxExecutor`, `sandbox_run_python`, and `run_python` names are consistent across config, factory, policy, tests, and agent tool code.
