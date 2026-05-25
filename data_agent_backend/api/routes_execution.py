from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import StrictInt

from data_agent_backend.api.common import ContextPayload, dump_result
from data_agent_backend.mcp.tools_execution import sandbox_run_python_impl, sql_run_query_impl
from data_agent_backend.models.common import BackendModel
from data_agent_backend.services.factory import BackendServices

from .deps import get_backend_services


router = APIRouter(prefix="/execution", tags=["execution"])


class SqlRunRequest(BackendModel):
    query: str
    run_id: str
    connection_id: str | None = None
    row_limit: int = 1000
    context: ContextPayload = None


class PythonRunRequest(BackendModel):
    code: str
    run_id: str
    input_artifact_ids: list[str] | None = None
    timeout_ms: StrictInt | None = None
    context: ContextPayload = None


@router.post("/sql")
def run_sql(payload: SqlRunRequest, services: BackendServices = Depends(get_backend_services)) -> dict:
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


@router.post("/python")
def run_python(payload: PythonRunRequest, services: BackendServices = Depends(get_backend_services)) -> dict:
    return dump_result(
        sandbox_run_python_impl(
            code=payload.code,
            run_id=payload.run_id,
            input_artifact_ids=payload.input_artifact_ids,
            timeout_ms=payload.timeout_ms,
            context=payload.context,
            services=services,
        )
    )
