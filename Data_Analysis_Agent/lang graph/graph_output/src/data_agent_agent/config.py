from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from dotenv import load_dotenv


DEFAULT_OPENAI_MODEL = "gpt-5.5-mini"
MYSQL_ENV_VARS = {
    "mysql_name": "DATA_AGENT_MYSQL_NAME",
    "mysql_host": "DATA_AGENT_MYSQL_HOST",
    "mysql_port": "DATA_AGENT_MYSQL_PORT",
    "mysql_database": "DATA_AGENT_MYSQL_DATABASE",
    "mysql_username": "DATA_AGENT_MYSQL_USERNAME",
    "mysql_password": "DATA_AGENT_MYSQL_PASSWORD",
}


class AgentConfigError(RuntimeError):
    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


@dataclass(frozen=True)
class AgentConfig:
    openai_api_key: str
    openai_model: str = DEFAULT_OPENAI_MODEL
    mcp_command: str = field(default_factory=lambda: sys.executable)
    mcp_args: list[str] = field(default_factory=lambda: ["-m", "data_agent_backend.mcp.server"])
    default_row_limit: int = 1000
    mysql_name: str | None = None
    mysql_host: str | None = None
    mysql_port: int | None = None
    mysql_database: str | None = None
    mysql_username: str | None = None
    mysql_password: str | None = None

    @classmethod
    def from_env(
        cls,
        *,
        openai_model: str | None = None,
        default_row_limit: int | None = None,
        require_api_key: bool = True,
        load_env: bool = True,
    ) -> "AgentConfig":
        if load_env:
            load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        model = (openai_model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()
        row_limit = default_row_limit if default_row_limit is not None else 1000
        mysql_port = cls._read_mysql_port()
        if require_api_key and not api_key:
            raise AgentConfigError("OPENAI_API_KEY가 설정되어 있지 않습니다. .env 또는 환경 변수에 값을 설정해 주세요.")
        if row_limit <= 0:
            raise AgentConfigError("--row-limit은 1 이상의 정수여야 합니다.")
        return cls(
            openai_api_key=api_key,
            openai_model=model,
            default_row_limit=row_limit,
            mysql_name=cls._read_env("DATA_AGENT_MYSQL_NAME"),
            mysql_host=cls._read_env("DATA_AGENT_MYSQL_HOST"),
            mysql_port=mysql_port,
            mysql_database=cls._read_env("DATA_AGENT_MYSQL_DATABASE"),
            mysql_username=cls._read_env("DATA_AGENT_MYSQL_USERNAME"),
            mysql_password=cls._read_env("DATA_AGENT_MYSQL_PASSWORD"),
        )

    @staticmethod
    def _read_env(name: str) -> str | None:
        value = os.getenv(name, "").strip()
        return value or None

    @classmethod
    def _read_mysql_port(cls) -> int | None:
        raw = cls._read_env("DATA_AGENT_MYSQL_PORT")
        if raw is None:
            return None
        try:
            port = int(raw)
        except ValueError as exc:
            raise AgentConfigError("DATA_AGENT_MYSQL_PORT는 정수여야 합니다.") from exc
        if port <= 0:
            raise AgentConfigError("DATA_AGENT_MYSQL_PORT는 1 이상의 정수여야 합니다.")
        return port

    def missing_mysql_env_vars(self) -> list[str]:
        missing: list[str] = []
        for attr, env_var in MYSQL_ENV_VARS.items():
            if getattr(self, attr) in (None, ""):
                missing.append(env_var)
        return missing

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
