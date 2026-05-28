from __future__ import annotations

import json
import os
from typing import Any


def trace_level() -> str:
    level = os.getenv("SQL_AGENT_DEMO_TRACE_LEVEL", "").lower()
    if level in {"quiet", "concise", "verbose"}:
        return level
    if os.getenv("SQL_AGENT_DEMO_TRACE", "").lower() in {"1", "true", "yes", "on"}:
        return "verbose"
    return "quiet"


def llm_raw_enabled() -> bool:
    return os.getenv("SQL_AGENT_SHOW_LLM_RAW", "").lower() in {"1", "true", "yes", "on"}


def emit_trace(stage: str, message: str, payload: dict[str, Any] | None = None) -> None:
    level = trace_level()
    if level == "quiet":
        return
    if level == "concise":
        _emit_concise_trace(stage, payload or {})
        return
    line = f"[trace] {stage}: {message}"
    print(line, flush=True)
    if payload:
        print(_format_payload(payload), flush=True)


def emit_llm_raw(raw_text: str) -> None:
    if not llm_raw_enabled():
        return
    print("[trace] llm.raw_response:", flush=True)
    print(raw_text, flush=True)


def _format_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _emit_concise_trace(stage: str, payload: dict[str, Any]) -> None:
    if stage == "supervisor.run_started":
        print(f"Run: {payload.get('run_id', '-')}", flush=True)
        if payload.get("datasource_id"):
            print(f"Datasource: {payload['datasource_id']}", flush=True)
        return
    if stage == "supervisor.plan_created":
        print(f"Route: {payload.get('route_kind', '-')}", flush=True)
        print(f"Planner: {payload.get('planner_mode', '-')}", flush=True)
        agents = payload.get("remaining_agents") or []
        if agents:
            print(f"Agents: {' -> '.join(agents)}", flush=True)
        return
    if stage == "planner.llm_request":
        catalog = "loaded" if payload.get("has_catalog") else "missing"
        print(f"Planner request: LLM (catalog: {catalog})", flush=True)
        return
    if stage == "planner.llm_parsed":
        print("Planner result: OK", flush=True)
        sql = payload.get("generated_sql")
        if sql:
            print(f"SQL: {sql}", flush=True)
        return
    if stage == "sql_agent.preview_ready":
        row_count = payload.get("row_count", "-")
        columns = payload.get("columns") or []
        print(f"SQL preview: {row_count} rows, {len(columns)} columns", flush=True)
        return
    if stage == "supervisor.validation_completed":
        print(f"Validation: {payload.get('status', '-')}", flush=True)
        return
    if stage == "supervisor.approval_gate":
        print(f"Approval required: {payload.get('approval_id', '-')}", flush=True)
        return
    if stage == "supervisor.resume_after_approval":
        print(f"Approval resolved: {payload.get('mart_id', '-')}", flush=True)
        return
    if stage == "supervisor.finalize":
        print("Status: completed", flush=True)
