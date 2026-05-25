from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from data_agent_backend.config import BackendConfig
from data_agent_backend.models.artifacts import ArtifactRef, ArtifactRegisterRequest, ArtifactType
from data_agent_backend.models.common import BackendError, JsonDict, utc_now_iso
from data_agent_backend.models.contexts import PolicyContext
from data_agent_backend.models.execution import ExecutionLimits, ExecutionResult, ExecutionStatus
from data_agent_backend.models.ids import UUID4IdGenerator
from data_agent_backend.services.artifact_registry import ArtifactRegistry
from data_agent_backend.services.artifact_store import ArtifactStore
from data_agent_backend.services.policy_engine import PolicyEngine
from data_agent_backend.storage.filesystem import ensure_child_path, safe_filename


class SandboxExecutor(Protocol):
    def run_python(
        self,
        code: str,
        inputs: list[ArtifactRef],
        limits: ExecutionLimits,
        context: PolicyContext,
    ) -> ExecutionResult: ...


class DisabledSandboxExecutor:
    sandbox_backend = "disabled"

    def __init__(self, policy_engine: PolicyEngine, id_generator: UUID4IdGenerator | None = None) -> None:
        self.policy_engine = policy_engine
        self.id_generator = id_generator or UUID4IdGenerator()

    def run_python(
        self,
        code: str,
        inputs: list[ArtifactRef],
        limits: ExecutionLimits,
        context: PolicyContext,
    ) -> ExecutionResult:
        decision = self.policy_engine.evaluate(
            "sandbox.python.run",
            "python",
            {
                "sandbox_backend": self.sandbox_backend,
                "code_bytes": len(code.encode("utf-8")),
                "input_artifact_ids": [item.artifact_id for item in inputs],
            },
            context,
        )
        if decision.requires_approval:
            return ExecutionResult(
                execution_id=self.id_generator.new_id("exec"),
                status=ExecutionStatus.approval_required,
                approval_id=context.approval_id,
                error_message=decision.reason,
            )
        if not decision.allowed:
            return ExecutionResult(
                execution_id=self.id_generator.new_id("exec"),
                status=ExecutionStatus.policy_blocked,
                error_message=decision.reason,
            )
        return ExecutionResult(
            execution_id=self.id_generator.new_id("exec"),
            status=ExecutionStatus.sandbox_not_configured,
            error_message="Python sandbox execution is disabled in this MVP.",
        )


class LocalPythonSandboxExecutor(DisabledSandboxExecutor):
    sandbox_backend = "local"

    def __init__(
        self,
        config: BackendConfig,
        policy_engine: PolicyEngine,
        artifact_registry: ArtifactRegistry,
        artifact_store: ArtifactStore,
        id_generator: UUID4IdGenerator | None = None,
    ) -> None:
        self.config = config
        self.artifact_registry = artifact_registry
        self.artifact_store = artifact_store
        super().__init__(policy_engine, id_generator)

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
                "sandbox_backend": self.sandbox_backend,
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

        try:
            timeout_ms = _effective_timeout_ms(self.config, limits)
        except BackendError as exc:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.error,
                error_message=f"{exc.code}: {exc.message}",
            )

        run_id = context.run_id or execution_id
        run_dir = ensure_child_path(self.config.sandbox_dir, self.config.sandbox_dir / "runs" / execution_id)
        paths = DockerSandboxExecutor._prepare_run_dir(self, run_dir, code, inputs)
        start_log = _write_execution_start_log(
            paths,
            execution_id=execution_id,
            run_id=run_id,
            sandbox_backend=self.sandbox_backend,
            timeout_ms=timeout_ms,
            inputs=inputs,
        )
        before = self._snapshot(paths["workspace"], paths["outputs"])
        result = self._run_subprocess(
            execution_id=execution_id,
            code_path=paths["code"] / "run.py",
            workspace_dir=paths["workspace"],
            inputs_dir=paths["inputs"],
            outputs_dir=paths["outputs"],
            timeout_ms=timeout_ms,
        )
        generated_artifact_ids: list[str] = []
        status = DockerSandboxExecutor._status_from_run_result(self, result)
        error_message = result.error_message

        try:
            generated_artifact_ids.extend(
                self._register_generated_files(run_id, execution_id, paths, before, inputs, context)
            )
            finish_log_for_artifact = _execution_finish_log_payload(
                execution_id=execution_id,
                status=status,
                result=result,
                artifact_ids_key="generated_artifact_ids",
                artifact_ids=generated_artifact_ids,
                error_message=error_message,
            )
            log_artifact = self._register_execution_log(
                run_id,
                execution_id,
                status,
                result,
                generated_artifact_ids,
                inputs,
                context,
                start_log,
                finish_log_for_artifact,
            )
            generated_artifact_ids.append(log_artifact.artifact_id)
        except BackendError as exc:
            status = ExecutionStatus.error
            error_message = f"{exc.code}: {exc.message}"
        _write_execution_finish_log(
            paths,
            execution_id=execution_id,
            status=status,
            result=result,
            created_artifact_ids=generated_artifact_ids,
            error_message=error_message,
        )

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

    def _run_subprocess(
        self,
        execution_id: str,
        code_path: Path,
        workspace_dir: Path,
        inputs_dir: Path,
        outputs_dir: Path,
        timeout_ms: int,
    ):
        executable = str(self.config.local_python_executable or sys.executable)
        env = self._base_subprocess_env()
        env.update(
            {
                "DATA_AGENT_INPUTS_DIR": str(inputs_dir.resolve()),
                "DATA_AGENT_WORKSPACE_DIR": str(workspace_dir.resolve()),
                "DATA_AGENT_OUTPUTS_DIR": str(outputs_dir.resolve()),
                "DATA_AGENT_EXECUTION_ID": execution_id,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                [executable, str(code_path.resolve())],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workspace_dir,
                env=env,
                **self._popen_process_group_kwargs(),
            )
            stdout, stderr = process.communicate(timeout=_timeout_seconds(timeout_ms))
            return DockerSandboxRunResult(
                exit_code=process.returncode,
                stdout=_decode_output(stdout),
                stderr=_decode_output(stderr),
                runtime_ms=int((time.monotonic() - started) * 1000),
            )
        except subprocess.TimeoutExpired as exc:
            self._terminate_process_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                stdout, stderr = exc.stdout, exc.stderr
            return DockerSandboxRunResult(
                exit_code=None,
                stdout=_decode_output(stdout or exc.stdout),
                stderr=_decode_output(stderr or exc.stderr),
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

    def _base_subprocess_env(self) -> dict[str, str]:
        allowed_names = {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
        }
        return {name: value for name, value in os.environ.items() if name.upper() in allowed_names}

    def _popen_process_group_kwargs(self) -> dict[str, int | bool]:
        if os.name == "nt":
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}

    def _terminate_process_tree(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

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
                artifact_type = self._artifact_type_for_path(path)
                record = self.artifact_registry.register_artifact(
                    ArtifactRegisterRequest(
                        run_id=run_id,
                        type=artifact_type,
                        content_bytes=path.read_bytes(),
                        filename=path.name,
                        thread_id=context.thread_id,
                        project_id=context.project_id,
                        created_by_tool="sandbox_run_python",
                        parent_ids=[item.artifact_id for item in inputs],
                        lineage_edge_type="generated_by_python",
                        metadata={
                            "sandbox_backend": self.sandbox_backend,
                            "execution_id": execution_id,
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
        result,
        generated_artifact_ids: list[str],
        inputs: list[ArtifactRef],
        context: PolicyContext,
        start_log: JsonDict,
        finish_log: JsonDict,
    ):
        log: JsonDict = {
            "sandbox_backend": self.sandbox_backend,
            "execution_id": execution_id,
            "run_id": run_id,
            "status": status.value,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "runtime_ms": result.runtime_ms,
            "artifacts": generated_artifact_ids,
            "generated_artifact_ids": generated_artifact_ids,
            "timed_out": result.timed_out,
            "error_message": result.error_message,
            "execution_start": start_log,
            "execution_finish": finish_log,
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
                    "sandbox_backend": self.sandbox_backend,
                    "execution_id": execution_id,
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

    def _snapshot(self, *roots: Path) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for root in roots:
            for path in self._iter_files(root):
                stat = path.stat()
                snapshot[self._snapshot_key(root, path)] = (stat.st_size, stat.st_mtime_ns)
        return snapshot

    def _iter_files(self, root: Path) -> list[Path]:
        return DockerSandboxExecutor._iter_files(self, root)

    def _snapshot_key(self, root: Path, path: Path) -> str:
        return DockerSandboxExecutor._snapshot_key(self, root, path)

    def _artifact_type_for_path(self, path: Path) -> ArtifactType:
        return DockerSandboxExecutor._artifact_type_for_path(self, path)


@dataclass(frozen=True)
class DockerSandboxRunRequest:
    execution_id: str
    container_name: str
    code_dir: Path
    inputs_dir: Path
    workspace_dir: Path
    outputs_dir: Path
    image: str
    timeout_ms: int
    memory: str
    cpus: float
    pids_limit: int
    tmpfs_size: str


@dataclass(frozen=True)
class DockerSandboxRunResult:
    exit_code: int | None
    stdout: str
    stderr: str
    runtime_ms: int
    timed_out: bool = False
    error_message: str | None = None


class DockerSandboxProvider:
    def run(self, request: DockerSandboxRunRequest) -> DockerSandboxRunResult:
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            request.container_name,
            "--network",
            "none",
            "--memory",
            request.memory,
            "--cpus",
            str(request.cpus),
            "--pids-limit",
            str(request.pids_limit),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            f"/tmp:rw,nosuid,nodev,size={request.tmpfs_size}",
            "--workdir",
            "/workspace",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-v",
            f"{request.code_dir.resolve()}:/code:ro",
            "-v",
            f"{request.inputs_dir.resolve()}:/inputs:ro",
            "-v",
            f"{request.workspace_dir.resolve()}:/workspace",
            "-v",
            f"{request.outputs_dir.resolve()}:/outputs",
            request.image,
            "python",
            "/code/run.py",
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=_timeout_seconds(request.timeout_ms),
            )
            return DockerSandboxRunResult(
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                runtime_ms=int((time.monotonic() - started) * 1000),
            )
        except subprocess.TimeoutExpired as exc:
            self._remove_container(request.container_name)
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
                error_message="Docker executable was not found.",
            )

    def _remove_container(self, container_name: str) -> None:
        subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True, text=True)


class DockerSandboxExecutor:
    def __init__(
        self,
        config: BackendConfig,
        policy_engine: PolicyEngine,
        artifact_registry: ArtifactRegistry,
        artifact_store: ArtifactStore,
        id_generator: UUID4IdGenerator | None = None,
        provider: DockerSandboxProvider | None = None,
    ) -> None:
        self.config = config
        self.policy_engine = policy_engine
        self.artifact_registry = artifact_registry
        self.artifact_store = artifact_store
        self.id_generator = id_generator or UUID4IdGenerator()
        self.provider = provider or DockerSandboxProvider()

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
                "sandbox_backend": "docker",
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

        try:
            timeout_ms = _effective_timeout_ms(self.config, limits)
        except BackendError as exc:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.error,
                error_message=f"{exc.code}: {exc.message}",
            )

        run_id = context.run_id or execution_id
        run_dir = ensure_child_path(self.config.sandbox_dir, self.config.sandbox_dir / "runs" / execution_id)
        paths = self._prepare_run_dir(run_dir, code, inputs)
        start_log = _write_execution_start_log(
            paths,
            execution_id=execution_id,
            run_id=run_id,
            sandbox_backend="docker",
            timeout_ms=timeout_ms,
            inputs=inputs,
        )
        before = self._snapshot(paths["workspace"], paths["outputs"])
        request = DockerSandboxRunRequest(
            execution_id=execution_id,
            container_name=f"data-agent-{execution_id.replace('_', '-')}",
            code_dir=paths["code"],
            inputs_dir=paths["inputs"],
            workspace_dir=paths["workspace"],
            outputs_dir=paths["outputs"],
            image=self.config.sandbox_image,
            timeout_ms=timeout_ms,
            memory=self.config.sandbox_memory,
            cpus=self.config.sandbox_cpus,
            pids_limit=self.config.sandbox_pids_limit,
            tmpfs_size=self.config.sandbox_tmpfs_size,
        )
        result = self.provider.run(request)
        generated_artifact_ids: list[str] = []
        status = self._status_from_run_result(result)
        error_message = result.error_message

        try:
            generated_artifact_ids.extend(self._register_generated_files(run_id, execution_id, paths, before, inputs, context))
            finish_log_for_artifact = _execution_finish_log_payload(
                execution_id=execution_id,
                status=status,
                result=result,
                artifact_ids_key="generated_artifact_ids",
                artifact_ids=generated_artifact_ids,
                error_message=error_message,
            )
            log_artifact = self._register_execution_log(
                run_id,
                execution_id,
                status,
                result,
                generated_artifact_ids,
                inputs,
                context,
                start_log,
                finish_log_for_artifact,
            )
            generated_artifact_ids.append(log_artifact.artifact_id)
        except BackendError as exc:
            status = ExecutionStatus.error
            error_message = f"{exc.code}: {exc.message}"
        _write_execution_finish_log(
            paths,
            execution_id=execution_id,
            status=status,
            result=result,
            created_artifact_ids=generated_artifact_ids,
            error_message=error_message,
        )

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
                artifact_type = self._artifact_type_for_path(path)
                record = self.artifact_registry.register_artifact(
                    ArtifactRegisterRequest(
                        run_id=run_id,
                        type=artifact_type,
                        content_bytes=path.read_bytes(),
                        filename=path.name,
                        thread_id=context.thread_id,
                        project_id=context.project_id,
                        created_by_tool="sandbox_run_python",
                        parent_ids=[item.artifact_id for item in inputs],
                        lineage_edge_type="generated_by_python",
                        metadata={
                            "execution_id": execution_id,
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
        start_log: JsonDict,
        finish_log: JsonDict,
    ):
        log: JsonDict = {
            "execution_id": execution_id,
            "run_id": run_id,
            "status": status.value,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "runtime_ms": result.runtime_ms,
            "artifacts": generated_artifact_ids,
            "generated_artifact_ids": generated_artifact_ids,
            "timed_out": result.timed_out,
            "error_message": result.error_message,
            "execution_start": start_log,
            "execution_finish": finish_log,
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


def _effective_timeout_ms(config: BackendConfig, limits: ExecutionLimits) -> int:
    timeout_ms = limits.timeout_ms if limits.timeout_ms is not None else config.default_execution_timeout_ms
    if timeout_ms <= 0:
        raise BackendError("VALIDATION_ERROR", "timeout_ms must be greater than 0.")
    if timeout_ms > config.max_execution_timeout_ms:
        raise BackendError(
            "VALIDATION_ERROR",
            f"timeout_ms must be less than or equal to {config.max_execution_timeout_ms}.",
        )
    return timeout_ms


def _timeout_seconds(timeout_ms: int) -> float:
    return timeout_ms / 1000


def _write_execution_start_log(
    paths: dict[str, Path],
    *,
    execution_id: str,
    run_id: str,
    sandbox_backend: str,
    timeout_ms: int,
    inputs: list[ArtifactRef],
) -> JsonDict:
    log: JsonDict = {
        "execution_id": execution_id,
        "run_id": run_id,
        "sandbox_backend": sandbox_backend,
        "timeout_ms": timeout_ms,
        "input_artifact_ids": [item.artifact_id for item in inputs],
        "code_path": str((paths["code"] / "run.py").resolve()),
        "started_at": utc_now_iso(),
        "status": "running",
    }
    _write_json_file(paths["logs"] / "execution_start.json", log)
    return log


def _write_execution_finish_log(
    paths: dict[str, Path],
    *,
    execution_id: str,
    status: ExecutionStatus,
    result: DockerSandboxRunResult,
    created_artifact_ids: list[str],
    error_message: str | None,
) -> None:
    log = _execution_finish_log_payload(
        execution_id=execution_id,
        status=status,
        result=result,
        artifact_ids_key="created_artifact_ids",
        artifact_ids=created_artifact_ids,
        error_message=error_message,
    )
    _write_json_file(paths["logs"] / "execution_finish.json", log)


def _execution_finish_log_payload(
    *,
    execution_id: str,
    status: ExecutionStatus,
    result: DockerSandboxRunResult,
    artifact_ids_key: str,
    artifact_ids: list[str],
    error_message: str | None,
) -> JsonDict:
    return {
        "execution_id": execution_id,
        "status": status.value,
        "exit_code": result.exit_code,
        "runtime_ms": result.runtime_ms,
        "stdout": result.stdout[:4000],
        "stderr": result.stderr[:4000],
        "error_message": error_message,
        "finished_at": utc_now_iso(),
        artifact_ids_key: list(artifact_ids),
    }


def _write_json_file(path: Path, payload: JsonDict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _decode_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
