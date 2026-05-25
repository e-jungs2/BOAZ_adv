from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import StrictInt

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
    python_timeout_ms: StrictInt | None = None
    metadata: JsonDict = {}


@router.post("/ask")
async def ask_agent(payload: AgentAskPayload, services: BackendServices = Depends(get_backend_services)) -> dict[str, Any]:
    try:
        config = None
        if payload.datasource_id is None:
            config = AgentConfig.from_env(
                openai_model=payload.model,
                default_row_limit=payload.row_limit,
                load_env=True,
            )
        runtime = AgentRuntime(config=config, tool_provider=InProcessBackendToolProvider(services))
        result = await runtime.run(
            AgentRunRequest(
                question=payload.question,
                datasource_id=payload.datasource_id,
                model=payload.model,
                row_limit=payload.row_limit,
                python_timeout_ms=payload.python_timeout_ms,
                metadata=payload.metadata,
                source="data-agent-api",
            )
        )
    except AgentConfigError as exc:
        return dump_result(ToolResult.failure("AGENT_CONFIG_ERROR", str(exc), getattr(exc, "details", {})))
    except AgentRuntimeError as exc:
        return dump_result(ToolResult.failure("AGENT_RUNTIME_ERROR", str(exc), getattr(exc, "details", {})))
    except Exception as exc:
        return dump_result(
            ToolResult.failure(
                "AGENT_RUNTIME_ERROR",
                "Agent runtime failed unexpectedly.",
                {"type": type(exc).__name__},
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
