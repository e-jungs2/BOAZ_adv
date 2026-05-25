from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from data_agent_backend.config import BackendConfig
from data_agent_backend.mcp.tools_execution import sandbox_run_python, sandbox_run_python_impl, sql_run_query_impl
from data_agent_backend.mcp.tools_workspace import workspace_write_text, workspace_write_text_impl
from data_agent_backend.models.artifacts import ArtifactRegisterRequest, ArtifactType
from data_agent_backend.models.contexts import PolicyContext
from data_agent_backend.models.execution import ExecutionLimits, ExecutionResult, ExecutionStatus
from data_agent_backend.services.factory import create_backend_services
from data_agent_backend.services.sandbox_executor import DockerSandboxExecutor, DockerSandboxRunResult


def test_workspace_mcp_public_signature_hides_services():
    signature = inspect.signature(workspace_write_text)
    assert "services" not in signature.parameters


def test_sandbox_mcp_public_signature_exposes_timeout_and_hides_services():
    signature = inspect.signature(sandbox_run_python)

    assert "timeout_ms" in signature.parameters
    assert signature.parameters["timeout_ms"].default is None
    assert list(signature.parameters).index("context") < list(signature.parameters).index("timeout_ms")
    assert "services" not in signature.parameters


def test_sandbox_mcp_public_call_preserves_positional_context(monkeypatch, services):
    monkeypatch.setattr("data_agent_backend.mcp.tools_execution.get_services", lambda: services)

    result = sandbox_run_python("print('x')", "run1", None, {"run_id": "ctx"})

    assert result.ok is True
    assert result.error is None


def test_sql_select_creates_query_and_result_artifacts(services):
    ref = services.sql_executor.run_sql_query("select 1 as x union all select 2 as x", "run1", row_limit=1, context=PolicyContext(run_id="run1"))
    assert ref.type.value == "sql_result"
    result = services.artifact_registry.get_artifact(ref.artifact_id)
    assert result.preview["row_count"] == 1
    lineage = services.artifact_registry.get_lineage(ref.artifact_id)
    assert lineage[0]["edge_type"] == "query_result_of"


def test_sql_blocks_dml_dangerous_and_multiple_statements(services):
    for query in ["delete from t", "pragma version", "select 1; select 2"]:
        result = sql_run_query_impl(query=query, run_id="run1", services=services)
        assert result.ok is False
        assert result.error.code == "POLICY_BLOCKED"


def test_sandbox_disabled_never_executes(services, tmp_path):
    marker = tmp_path / "marker.txt"
    result = services.sandbox_executor.run_python(
        f"open({str(marker)!r}, 'w').write('bad')",
        [],
        ExecutionLimits(),
        PolicyContext(run_id="run1", approval_id="approved"),
    )
    assert result.status == ExecutionStatus.sandbox_not_configured
    assert not marker.exists()


def test_docker_sandbox_collects_new_workspace_and_output_files(services):
    class FakeDockerProvider:
        def run(self, request):
            nested = request.workspace_dir / "nested"
            nested.mkdir(parents=True)
            (nested / "report.txt").write_text("created in workspace", encoding="utf-8")
            (request.outputs_dir / "result.csv").write_text("x\n1\n", encoding="utf-8")
            return DockerSandboxRunResult(exit_code=0, stdout="ok\n", stderr="", runtime_ms=12)

    executor = DockerSandboxExecutor(
        services.config,
        services.policy_engine,
        services.artifact_registry,
        services.artifact_store,
        provider=FakeDockerProvider(),
    )

    result = executor.run_python(
        "print('ok')",
        [],
        ExecutionLimits(timeout_ms=1000),
        PolicyContext(run_id="run1", approval_id="approved"),
    )

    assert result.status == ExecutionStatus.success
    records = [services.artifact_registry.get_artifact(artifact_id) for artifact_id in result.created_artifact_ids]
    generated = [record for record in records if record.type.value != "execution_log"]
    assert {record.metadata["sandbox_relative_path"] for record in generated} == {"nested/report.txt", "result.csv"}
    assert {record.metadata["sandbox_root"] for record in generated} == {"workspace", "outputs"}
    assert any(record.type.value == "execution_log" for record in records)


def test_docker_sandbox_requires_approval_before_provider_runs(services):
    class FailingDockerProvider:
        def run(self, request):
            raise AssertionError("provider should not run without approval")

    executor = DockerSandboxExecutor(
        services.config,
        services.policy_engine,
        services.artifact_registry,
        services.artifact_store,
        provider=FailingDockerProvider(),
    )

    result = executor.run_python("print('nope')", [], ExecutionLimits(), PolicyContext(run_id="run1"))

    assert result.status == ExecutionStatus.approval_required
    assert result.created_artifact_ids == []


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


def test_mcp_tools_return_tool_result_envelope(services):
    ok = workspace_write_text_impl(path="/workspace/a.txt", content="hello", services=services)
    assert ok.ok is True
    blocked = workspace_write_text_impl(path="/artifacts/a.txt", content="hello", services=services)
    assert blocked.ok is False
    assert blocked.error.code == "POLICY_BLOCKED"
    sandbox = sandbox_run_python_impl(code="print('nope')", run_id="run1", services=services)
    assert sandbox.ok is True
    assert sandbox.data["status"] == "approval_required"


def test_sandbox_mcp_impl_passes_timeout_to_executor_limits(services):
    captured_limits: list[ExecutionLimits] = []

    class CapturingSandboxExecutor:
        def run_python(self, code, inputs, limits, context):
            captured_limits.append(limits)
            return ExecutionResult(execution_id="exec_1", status=ExecutionStatus.success)

    services.sandbox_executor = CapturingSandboxExecutor()

    result = sandbox_run_python_impl(
        code="print('ok')",
        run_id="run1",
        timeout_ms=4321,
        services=services,
    )

    assert result.ok is True
    assert captured_limits[0].timeout_ms == 4321


@pytest.mark.parametrize("timeout_ms", [0, 600_001])
def test_sandbox_mcp_impl_rejects_timeout_range_before_executor_runs(services, timeout_ms):
    class FailingSandboxExecutor:
        def run_python(self, code, inputs, limits, context):
            raise AssertionError("executor should not run for invalid timeout")

    services.sandbox_executor = FailingSandboxExecutor()

    result = sandbox_run_python_impl(
        code="print('nope')",
        run_id="run1",
        timeout_ms=timeout_ms,
        services=services,
    )

    assert result.ok is False
    assert result.error.code == "VALIDATION_ERROR"


def test_sandbox_mcp_impl_rejects_timeout_type_before_executor_runs(services):
    class FailingSandboxExecutor:
        def run_python(self, code, inputs, limits, context):
            raise AssertionError("executor should not run for invalid timeout")

    services.sandbox_executor = FailingSandboxExecutor()

    result = sandbox_run_python_impl(
        code="print('nope')",
        run_id="run1",
        timeout_ms="bad",
        services=services,
    )

    assert result.ok is False
    assert result.error.code == "VALIDATION_ERROR"


def test_backend_config_reads_sandbox_backend_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_AGENT_SANDBOX_BACKEND", "local")
    monkeypatch.setenv("DATA_AGENT_LOCAL_PYTHON_EXECUTABLE", "python-custom")

    config = BackendConfig.from_env(base_data_dir=tmp_path / ".data_agent", load_env=False)

    assert config.sandbox_backend == "local"
    assert str(config.local_python_executable) == "python-custom"


def test_python_execution_limits_default_to_configured_timeout(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent")

    assert config.default_execution_timeout_ms == 300_000
    assert config.max_execution_timeout_ms == 600_000
    assert ExecutionLimits().timeout_ms is None


def test_backend_config_rejects_unknown_sandbox_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_AGENT_SANDBOX_BACKEND", "unsafe")

    with pytest.raises(ValueError, match="DATA_AGENT_SANDBOX_BACKEND"):
        BackendConfig.from_env(base_data_dir=tmp_path / ".data_agent", load_env=False)


def test_docker_sandbox_default_run_uses_configured_timeout(tmp_path):
    config = BackendConfig(
        base_data_dir=tmp_path / ".data_agent",
        default_execution_timeout_ms=1234,
    )
    services = create_backend_services(config)
    captured_timeout_ms: list[int] = []

    class FakeDockerProvider:
        def run(self, request):
            captured_timeout_ms.append(request.timeout_ms)
            return DockerSandboxRunResult(exit_code=0, stdout="ok\n", stderr="", runtime_ms=12)

    executor = DockerSandboxExecutor(
        services.config,
        services.policy_engine,
        services.artifact_registry,
        services.artifact_store,
        provider=FakeDockerProvider(),
    )

    result = executor.run_python(
        "print('ok')",
        [],
        ExecutionLimits(),
        PolicyContext(run_id="run1", approval_id="approved"),
    )

    assert result.status == ExecutionStatus.success
    assert captured_timeout_ms == [1234]


def test_docker_sandbox_explicit_timeout_overrides_config(tmp_path):
    config = BackendConfig(
        base_data_dir=tmp_path / ".data_agent",
        default_execution_timeout_ms=1234,
    )
    services = create_backend_services(config)
    captured_timeout_ms: list[int] = []

    class FakeDockerProvider:
        def run(self, request):
            captured_timeout_ms.append(request.timeout_ms)
            return DockerSandboxRunResult(exit_code=0, stdout="ok\n", stderr="", runtime_ms=12)

    executor = DockerSandboxExecutor(
        services.config,
        services.policy_engine,
        services.artifact_registry,
        services.artifact_store,
        provider=FakeDockerProvider(),
    )

    result = executor.run_python(
        "print('ok')",
        [],
        ExecutionLimits(timeout_ms=4321),
        PolicyContext(run_id="run1", approval_id="approved"),
    )

    assert result.status == ExecutionStatus.success
    assert captured_timeout_ms == [4321]


def test_factory_selects_local_python_executor(tmp_path):
    from data_agent_backend.services.sandbox_executor import LocalPythonSandboxExecutor

    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    assert isinstance(services.sandbox_executor, LocalPythonSandboxExecutor)


def test_local_python_executor_uses_configured_python_executable(monkeypatch, tmp_path):
    configured_python = tmp_path / "analysis-python.exe"
    config = BackendConfig(
        base_data_dir=tmp_path / ".data_agent",
        sandbox_backend="local",
        local_python_executable=configured_python,
    )
    services = create_backend_services(config)
    captured_popen_args = []

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout):
            return b"ok\n", b""

    def fake_popen(args, **kwargs):
        captured_popen_args.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr("data_agent_backend.services.sandbox_executor.subprocess.Popen", fake_popen)

    result = services.sandbox_executor.run_python(
        "print('ok')",
        [],
        ExecutionLimits(timeout_ms=5000),
        PolicyContext(run_id="run1"),
    )

    assert result.status == ExecutionStatus.success
    assert captured_popen_args[0][0][0] == str(configured_python)


def test_local_python_executor_rejects_non_positive_timeout(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        "print('nope')",
        [],
        ExecutionLimits(timeout_ms=0),
        PolicyContext(run_id="run1"),
    )

    assert result.status == ExecutionStatus.error
    assert result.error_message is not None
    assert result.error_message.startswith("VALIDATION_ERROR:")
    assert "timeout_ms" in result.error_message


def test_local_python_executor_rejects_timeout_above_max(tmp_path):
    config = BackendConfig(
        base_data_dir=tmp_path / ".data_agent",
        sandbox_backend="local",
        max_execution_timeout_ms=1000,
    )
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        "print('nope')",
        [],
        ExecutionLimits(timeout_ms=1001),
        PolicyContext(run_id="run1"),
    )

    assert result.status == ExecutionStatus.error
    assert result.error_message is not None
    assert result.error_message.startswith("VALIDATION_ERROR:")
    assert "1000" in result.error_message


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


def test_local_python_executor_writes_start_and_finish_logs(tmp_path):
    config = BackendConfig(
        base_data_dir=tmp_path / ".data_agent",
        sandbox_backend="local",
        default_execution_timeout_ms=2345,
    )
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        "print('hello from logs')",
        [],
        ExecutionLimits(),
        PolicyContext(run_id="run1"),
    )

    run_dir = config.sandbox_dir / "runs" / result.execution_id
    start_log = json.loads((run_dir / "logs" / "execution_start.json").read_text(encoding="utf-8"))
    finish_log = json.loads((run_dir / "logs" / "execution_finish.json").read_text(encoding="utf-8"))

    assert start_log["execution_id"] == result.execution_id
    assert start_log["run_id"] == "run1"
    assert start_log["sandbox_backend"] == "local"
    assert start_log["timeout_ms"] == 2345
    assert start_log["input_artifact_ids"] == []
    assert start_log["code_path"].endswith("run.py")
    assert start_log["started_at"]
    assert start_log["status"] == "running"
    assert finish_log["execution_id"] == result.execution_id
    assert finish_log["status"] == "success"
    assert finish_log["exit_code"] == 0
    assert finish_log["runtime_ms"] >= 0
    assert finish_log["stdout"].replace("\r\n", "\n") == "hello from logs\n"
    assert finish_log["stderr"] == ""
    assert finish_log["error_message"] is None
    assert finish_log["finished_at"]
    assert finish_log["created_artifact_ids"] == result.created_artifact_ids


def test_local_python_executor_preserves_start_and_finish_log_in_artifact_when_run_dir_is_removed(tmp_path):
    config = BackendConfig(
        base_data_dir=tmp_path / ".data_agent",
        sandbox_backend="local",
        sandbox_keep_run_dirs=False,
        default_execution_timeout_ms=2345,
    )
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        """
import os
from pathlib import Path

Path(os.environ["DATA_AGENT_OUTPUTS_DIR"]).joinpath("result.txt").write_text("done", encoding="utf-8")
print("cleanup mode")
""",
        [],
        ExecutionLimits(),
        PolicyContext(run_id="run1"),
    )

    run_dir = config.sandbox_dir / "runs" / result.execution_id
    assert result.status == ExecutionStatus.success
    assert not run_dir.exists()

    records = [services.artifact_registry.get_artifact(artifact_id) for artifact_id in result.created_artifact_ids]
    log_record = next(record for record in records if record.type.value == "execution_log")
    log_payload = json.loads(Path(log_record.local_path).read_text(encoding="utf-8"))
    generated_artifact_ids = [
        record.artifact_id for record in records if record.type.value != "execution_log"
    ]

    assert log_payload["execution_start"]["run_id"] == "run1"
    assert log_payload["execution_start"]["timeout_ms"] == 2345
    assert log_payload["execution_start"]["input_artifact_ids"] == []
    assert log_payload["execution_start"]["started_at"]
    assert log_payload["execution_finish"]["finished_at"]
    assert log_payload["execution_finish"]["generated_artifact_ids"] == generated_artifact_ids
    assert log_payload["execution_finish"]["status"] == "success"


def test_local_python_executor_can_read_input_artifact(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)
    input_record = services.artifact_registry.register_artifact(
        ArtifactRegisterRequest(
            run_id="run1",
            type=ArtifactType.dataset,
            content_text="value\n41\n",
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
    derived = [
        services.artifact_registry.get_artifact(item)
        for item in result.created_artifact_ids
        if item != input_record.artifact_id
    ]
    text_records = [record for record in derived if record.metadata.get("sandbox_relative_path") == "derived.txt"]
    assert len(text_records) == 1
    lineage = services.artifact_registry.get_lineage(text_records[0].artifact_id)
    assert lineage[0]["parent_id"] == input_record.artifact_id
    assert lineage[0]["edge_type"] == "generated_by_python"


def test_local_python_executor_does_not_inherit_secret_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai")
    monkeypatch.setenv("DATA_AGENT_MYSQL_PASSWORD", "secret-mysql")
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        """
import os
from pathlib import Path

outputs = Path(os.environ["DATA_AGENT_OUTPUTS_DIR"])
outputs.joinpath("env.txt").write_text(
    f"openai={os.environ.get('OPENAI_API_KEY')}\\n"
    f"mysql={os.environ.get('DATA_AGENT_MYSQL_PASSWORD')}\\n",
    encoding="utf-8",
)
print(os.environ.get("OPENAI_API_KEY"))
""",
        [],
        ExecutionLimits(timeout_ms=5000),
        PolicyContext(run_id="run1"),
    )

    assert result.status == ExecutionStatus.success
    assert "secret-openai" not in result.stdout
    records = [services.artifact_registry.get_artifact(artifact_id) for artifact_id in result.created_artifact_ids]
    env_record = next(record for record in records if record.metadata.get("sandbox_relative_path") == "env.txt")
    content = Path(env_record.local_path).read_text(encoding="utf-8")
    assert "secret-openai" not in content
    assert "secret-mysql" not in content
    assert "openai=None" in content
    assert "mysql=None" in content


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


def test_local_python_executor_writes_finish_log_on_timeout(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        "import time; print('before timeout', flush=True); time.sleep(2)",
        [],
        ExecutionLimits(timeout_ms=100),
        PolicyContext(run_id="run1"),
    )

    run_dir = config.sandbox_dir / "runs" / result.execution_id
    finish_log = json.loads((run_dir / "logs" / "execution_finish.json").read_text(encoding="utf-8"))

    assert result.status == ExecutionStatus.timeout
    assert finish_log["execution_id"] == result.execution_id
    assert finish_log["status"] == "timeout"
    assert finish_log["exit_code"] is None
    assert finish_log["runtime_ms"] >= 100
    assert finish_log["stdout"].startswith("before timeout")
    assert finish_log["error_message"] == "Python sandbox execution timed out."
    assert finish_log["finished_at"]
    assert finish_log["created_artifact_ids"] == result.created_artifact_ids


def test_local_python_executor_decodes_invalid_stdout_bytes(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent", sandbox_backend="local")
    services = create_backend_services(config)

    result = services.sandbox_executor.run_python(
        'import sys; sys.stdout.buffer.write(b"\\xff")',
        [],
        ExecutionLimits(timeout_ms=5000),
        PolicyContext(run_id="run1"),
    )

    assert result.status == ExecutionStatus.success
    assert result.stdout
    assert "\ufffd" in result.stdout
