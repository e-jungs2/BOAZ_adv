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
    default_execution_timeout_ms: int = 300_000
    max_execution_timeout_ms: int = 600_000
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

    @property
    def workspace_dir(self) -> Path:
        return self.base_data_dir / "workspace"

    @property
    def artifact_dir(self) -> Path:
        return self.base_data_dir / "artifacts"

    @property
    def catalog_dir(self) -> Path:
        return self.base_data_dir / "catalog"

    @property
    def skills_dir(self) -> Path:
        return self.base_data_dir / "skills"

    @property
    def exports_dir(self) -> Path:
        return self.base_data_dir / "exports"

    @property
    def secrets_dir(self) -> Path:
        return self.base_data_dir / "secrets"

    @property
    def sandbox_dir(self) -> Path:
        return self.base_data_dir / "sandbox"

    @property
    def db_path(self) -> Path:
        return self.sqlite_path or self.base_data_dir / "backend.sqlite"

    def ensure_dirs(self) -> None:
        for path in (
            self.base_data_dir,
            self.workspace_dir,
            self.artifact_dir,
            self.catalog_dir,
            self.skills_dir,
            self.exports_dir,
            self.secrets_dir,
            self.sandbox_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
