from __future__ import annotations

import inspect
import json
from typing import Any

from langchain_core.tools import BaseTool, tool


class AgentToolError(RuntimeError):
    pass


async def call_raw_tool(raw_tool: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if hasattr(raw_tool, "ainvoke"):
        result = raw_tool.ainvoke(payload)
        if inspect.isawaitable(result):
            result = await result
        return normalize_tool_result(result)
    if hasattr(raw_tool, "invoke"):
        result = raw_tool.invoke(payload)
        if inspect.isawaitable(result):
            result = await result
        return normalize_tool_result(result)
    if callable(raw_tool):
        result = raw_tool(**payload)
        if inspect.isawaitable(result):
            result = await result
        return normalize_tool_result(result)
    raise AgentToolError(f"호출할 수 없는 raw tool입니다: {raw_tool!r}")


def normalize_tool_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        result = result.model_dump(mode="json")
    if isinstance(result, list):
        if len(result) == 1 and isinstance(result[0], dict) and result[0].get("type") == "text":
            text = result[0].get("text")
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    return {"ok": True, "data": text, "error": None}
                return normalize_tool_result(parsed)
        return {"ok": True, "data": result, "error": None}
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return {"ok": True, "data": result, "error": None}
        result = parsed
    if isinstance(result, dict):
        if "ok" in result:
            return result
        return {"ok": True, "data": result, "error": None}
    return {"ok": True, "data": result, "error": None}


def error_payload(result: dict[str, Any]) -> dict[str, Any]:
    error = result.get("error") or {}
    details = error.get("details") or {}
    payload = {
        "ok": False,
        "code": error.get("code", "UNKNOWN_ERROR"),
        "message": error.get("message", "Backend tool call failed."),
        "details": details,
    }
    for key in ("suggestion", "retryable", "query_artifact_id"):
        if key in details:
            payload[key] = details[key]
    return payload


def build_agent_tools(
    raw_tools: dict[str, Any],
    *,
    datasource_id: str,
    run_id: str,
    default_row_limit: int = 1000,
    default_python_timeout_ms: int | None = None,
) -> list[BaseTool]:
    raw_catalog_summary = raw_tools["datasource_get_catalog_summary"]
    raw_analysis_context = raw_tools.get("analysis_build_context")
    raw_query = raw_tools["datasource_query"]
    raw_python = raw_tools["sandbox_run_python"]

    @tool
    async def get_catalog_summary() -> dict[str, Any]:
        """현재 datasource의 테이블과 컬럼 요약을 조회한다."""
        result = await call_raw_tool(raw_catalog_summary, {"datasource_id": datasource_id})
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error")}
        return result.get("data") or {}

    agent_tools: list[BaseTool] = [get_catalog_summary]

    if raw_analysis_context is not None:

        @tool
        async def build_analysis_context(question: str, limit: int = 10) -> dict[str, Any]:
            """현재 질문과 관련된 catalog, profile, semantic, mart, join 후보를 조회한다."""
            effective_limit = limit if limit and limit > 0 else 10
            result = await call_raw_tool(
                raw_analysis_context,
                {
                    "datasource_id": datasource_id,
                    "question": question,
                    "limit": effective_limit,
                },
            )
            if not result.get("ok"):
                return error_payload(result)
            return result.get("data") or {}

        agent_tools.append(build_analysis_context)

    @tool
    async def run_sql(query: str, row_limit: int = 1000) -> dict[str, Any]:
        """현재 datasource에서 단일 read-only SELECT SQL을 실행한다."""
        limit = row_limit if row_limit and row_limit > 0 else default_row_limit
        result = await call_raw_tool(
            raw_query,
            {
                "datasource_id": datasource_id,
                "query": query,
                "run_id": run_id,
                "row_limit": limit,
            },
        )
        if not result.get("ok"):
            return error_payload(result)
        data = result.get("data") or {}
        return {
            "artifact_ref": data.get("artifact_ref"),
            "columns": data.get("columns", []),
            "row_count": data.get("row_count", 0),
            "sample_rows": data.get("sample_rows", []),
        }

    agent_tools.append(run_sql)

    @tool
    async def run_python(
        code: str,
        input_artifact_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """SQL 결과 artifact를 입력으로 받아 Python 전처리, 통계 계산, 시각화, 파일 생성을 실행한다."""
        payload: dict[str, Any] = {
            "code": code,
            "run_id": run_id,
            "input_artifact_ids": input_artifact_ids or [],
        }
        if default_python_timeout_ms is not None:
            payload["timeout_ms"] = default_python_timeout_ms
        result = await call_raw_tool(raw_python, payload)
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
    return agent_tools
