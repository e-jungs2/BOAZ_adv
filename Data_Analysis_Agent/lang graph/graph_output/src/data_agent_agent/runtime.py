from __future__ import annotations

import inspect
import os
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol

from dotenv import load_dotenv

from data_agent_agent.config import DEFAULT_OPENAI_MODEL, AgentConfig, AgentConfigError
from data_agent_agent.deep_agent import create_data_agent
from data_agent_agent.mcp_client import require_backend_tools
from data_agent_agent.tool_provider import BackendToolProvider, MCPBackendToolProvider
from data_agent_agent.tools import build_agent_tools, call_raw_tool


MIN_PYTHON_TIMEOUT_MS = 1
MAX_PYTHON_TIMEOUT_MS = 600_000
PYTHON_TIMEOUT_ERROR_MESSAGE = (
    f"python_timeout_ms must be an integer from {MIN_PYTHON_TIMEOUT_MS} to {MAX_PYTHON_TIMEOUT_MS} ms."
)


class AgentRuntimeError(RuntimeError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


@dataclass(frozen=True)
class AgentRunRequest:
    question: str
    datasource_id: str | None = None
    model: str | None = None
    row_limit: int | None = None
    python_timeout_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "data-agent-agent"


@dataclass(frozen=True)
class AgentRunResult:
    answer: str
    run_id: str
    datasource_id: str
    raw_result: Any


AgentFactory = Callable[..., Any]


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


class AgentRuntime:
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
        self.agent_factory = agent_factory
        self.agent_runner = agent_runner or DeepAgentsRunner(agent_factory)

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        validate_python_timeout_ms(request.python_timeout_ms)
        config = self._config_for_request(request)
        os.environ.setdefault("OPENAI_API_KEY", config.openai_api_key)
        if request.datasource_id is None:
            config.mysql_create_payload()

        raw_tools = require_backend_tools(await self.tool_provider.load_tools(config))
        resolved_datasource_id = await resolve_datasource_id(raw_tools, config, request.datasource_id)
        datasource_source = "cli" if request.datasource_id else "env"
        run_id = await self._create_run(
            raw_tools,
            config=config,
            request=request,
            datasource_id=resolved_datasource_id,
            datasource_source=datasource_source,
        )

        tools = build_agent_tools(
            raw_tools,
            datasource_id=resolved_datasource_id,
            run_id=run_id,
            default_row_limit=config.default_row_limit,
            default_python_timeout_ms=request.python_timeout_ms,
        )
        runner_result = await self.agent_runner.run(
            question=request.question,
            model=config.openai_model,
            tools=tools,
            metadata={
                **request.metadata,
                "run_id": run_id,
                "datasource_id": resolved_datasource_id,
                "source": request.source,
                "model": config.openai_model,
                "trace_name": self._trace_name(request.source, resolved_datasource_id, run_id),
            },
        )
        return AgentRunResult(
            answer=runner_result["answer"],
            run_id=run_id,
            datasource_id=resolved_datasource_id,
            raw_result=runner_result["raw_result"],
        )

    def _trace_name(self, source: str, datasource_id: str, run_id: str) -> str:
        return f"data-agent:{source}:{datasource_id}:{run_id}"

    def _config_for_request(self, request: AgentRunRequest) -> AgentConfig:
        if self.config is None:
            if request.datasource_id is not None:
                return self._explicit_datasource_config_from_env(request)
            return AgentConfig.from_env(openai_model=request.model, default_row_limit=request.row_limit)
        if request.row_limit is not None and request.row_limit <= 0:
            raise AgentConfigError("row_limit은 1 이상의 정수여야 합니다.")
        updates: dict[str, Any] = {}
        if request.model is not None:
            updates["openai_model"] = request.model
        if request.row_limit is not None:
            updates["default_row_limit"] = request.row_limit
        if not updates:
            return self.config
        return replace(self.config, **updates)

    def _explicit_datasource_config_from_env(self, request: AgentRunRequest) -> AgentConfig:
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        model = (request.model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()
        row_limit = request.row_limit if request.row_limit is not None else 1000
        if not api_key:
            raise AgentConfigError("OPENAI_API_KEY가 설정되어 있지 않습니다.")
        if row_limit <= 0:
            raise AgentConfigError("row_limit은 1 이상의 정수여야 합니다.")
        return AgentConfig(
            openai_api_key=api_key,
            openai_model=model,
            default_row_limit=row_limit,
        )

    async def _create_run(
        self,
        raw_tools: dict[str, Any],
        *,
        config: AgentConfig,
        request: AgentRunRequest,
        datasource_id: str,
        datasource_source: str,
    ) -> str:
        metadata = {
            **request.metadata,
            "source": request.source,
            "datasource_source": datasource_source,
            "datasource_id": datasource_id,
            "question": request.question,
            "model": config.openai_model,
            "trace_name": self._trace_name(request.source, datasource_id, "pending"),
        }
        run_result = await call_raw_tool(raw_tools["run_create"], {"metadata": metadata})
        if not run_result.get("ok"):
            _raise_backend_runtime_error("run_create", run_result)
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
        _raise_backend_runtime_error("datasource_list", listed)

    existing_datasource_id = _find_matching_mysql_datasource(listed.get("data"), mysql_payload)
    datasource_id = existing_datasource_id
    if datasource_id is None:
        created = await call_raw_tool(raw_tools["datasource_create"], mysql_payload)
        if not created.get("ok"):
            _raise_backend_runtime_error("datasource_create", created)
        datasource_id = (created.get("data") or {}).get("datasource_id")
        if not datasource_id:
            raise AgentRuntimeError("datasource_create 응답에 datasource_id가 없습니다.")

    tested = await call_raw_tool(raw_tools["datasource_test"], {"datasource_id": datasource_id})
    if not tested.get("ok"):
        _raise_backend_runtime_error("datasource_test", tested)
    test_data = tested.get("data") or {}
    if test_data.get("ok") is False:
        message = test_data.get("message") or "Datasource 연결 테스트에 실패했습니다."
        raise AgentRuntimeError(f"datasource_test 실패: {message}")

    refreshed = await call_raw_tool(raw_tools["datasource_refresh_catalog"], {"datasource_id": datasource_id})
    if not refreshed.get("ok"):
        _raise_backend_runtime_error("datasource_refresh_catalog", refreshed)

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


def _backend_error_message(step: str, result: dict[str, Any]) -> str:
    error = result.get("error") or {}
    code = error.get("code", "UNKNOWN_ERROR")
    message = error.get("message", "")
    return f"{step} 실패: {code} - {message}"


def _backend_error_details(step: str, result: dict[str, Any]) -> dict[str, Any]:
    error = result.get("error") or {}
    raw_details = error.get("details")
    details = dict(raw_details) if isinstance(raw_details, dict) else {}
    details.setdefault("backend_code", error.get("code", "UNKNOWN_ERROR"))
    details.setdefault("backend_message", error.get("message", ""))
    details.setdefault("bootstrap_step", step)
    return details


def _raise_backend_runtime_error(step: str, result: dict[str, Any]) -> None:
    raise AgentRuntimeError(_backend_error_message(step, result), _backend_error_details(step, result))


def validate_python_timeout_ms(value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise AgentConfigError(
            PYTHON_TIMEOUT_ERROR_MESSAGE,
            {"field": "python_timeout_ms", "min": MIN_PYTHON_TIMEOUT_MS, "max": MAX_PYTHON_TIMEOUT_MS},
        )
    if value < MIN_PYTHON_TIMEOUT_MS or value > MAX_PYTHON_TIMEOUT_MS:
        raise AgentConfigError(
            PYTHON_TIMEOUT_ERROR_MESSAGE,
            {"field": "python_timeout_ms", "min": MIN_PYTHON_TIMEOUT_MS, "max": MAX_PYTHON_TIMEOUT_MS},
        )


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
