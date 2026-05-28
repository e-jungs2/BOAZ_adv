from __future__ import annotations

import json
from typing import Any

from data_agent_backend.models.common import BackendError

from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime
from DATA_Analyst_Assistant_Agent.agents.sql.mart import (
    build_mart_candidate,
    needs_mart_candidate,
    register_mart_candidate_artifact,
)
from DATA_Analyst_Assistant_Agent.agents.sql.planner import SQLPlan, build_sql_plan
from DATA_Analyst_Assistant_Agent.agents.sql.self_check import run_sql_self_check
from DATA_Analyst_Assistant_Agent.models import (
    AgentEnvelope,
    AgentStatus,
    ApprovalRequirement,
    BusinessFlag,
    LocalCheck,
    OrchestrationState,
    ValidationBlock,
)
from DATA_Analyst_Assistant_Agent.tracing import emit_trace


class SQLAgent:
    name = "sql_agent"

    def run(self, state: OrchestrationState, runtime: AgentRuntime) -> AgentEnvelope:
        plan = state.plan
        context = runtime.context(state, node_name=self.name, tool_name="sql_agent.preview")
        emit_trace(
            "sql_agent.start",
            "Starting SQL agent.",
            {"route_kind": state.route_kind, "planner_mode": state.planner_mode, "user_query": state.user_query},
        )

        # 1. Build SQL plan
        try:
            sql_plan = build_sql_plan(state.user_query, plan)
        except Exception as exc:
            error_payload = self._build_retry_error_payload(state, state.user_query, exc)
            state.error_state = error_payload
            if plan is not None:
                plan.retry_context = error_payload
            return AgentEnvelope(
                status=AgentStatus.failed,
                agent_name=self.name,
                summary=f"SQL planning failed: {error_payload['message']}",
                validation=ValidationBlock(
                    local_checks=[
                        LocalCheck(
                            name="planner_execution",
                            passed=False,
                            severity="error",
                            detail=error_payload["message"],
                        )
                    ]
                ),
                retry_hint={"retryable": False, "suggested_action": "configure_llm_planner", "reason_code": error_payload["code"]},
                next_handoff="validation_agent",
            )
        emit_trace(
            "sql_agent.plan_ready",
            "SQL plan built.",
            {
                "planner_mode": sql_plan.planner_mode,
                "selected_tables": sql_plan.selected_tables,
                "selected_columns": sql_plan.selected_columns,
                "generated_sql": sql_plan.generated_sql,
            },
        )
        state.generated_sql = sql_plan.generated_sql
        state.planner_mode = str(sql_plan.planner_mode)
        if plan is not None:
            plan.generated_sql = sql_plan.generated_sql
            plan.planner_mode = "llm" if sql_plan.planner_mode == "llm" else "deterministic"

        # 2. Pre-execution self-check
        pre_checks = run_sql_self_check(sql_plan.generated_sql)
        if not all(c.passed for c in pre_checks):
            return self._failed_envelope(pre_checks, sql_plan)

        # 3. Execute preview through backend
        try:
            preview_ref = runtime.adapter.run_sql_preview(
                state.run_id,
                sql_plan.generated_sql,
                datasource_id=state.datasource_id,
                context=context,
            )
            emit_trace(
                "sql_agent.preview_ready",
                "SQL preview artifact created.",
                {
                    "artifact_id": preview_ref.artifact_id,
                    "row_count": preview_ref.preview.get("row_count"),
                    "columns": preview_ref.preview.get("columns"),
                },
            )
        except Exception as exc:
            error_payload = self._build_retry_error_payload(state, sql_plan.generated_sql, exc)
            state.error_state = error_payload
            if plan is not None:
                plan.retry_context = error_payload
            return AgentEnvelope(
                status=AgentStatus.failed,
                agent_name=self.name,
                summary=f"SQL preview failed: {error_payload['message']}",
                validation=ValidationBlock(
                    local_checks=[
                        LocalCheck(
                            name="preview_execution",
                            passed=False,
                            severity="error",
                            detail=error_payload["message"],
                        )
                    ]
                ),
                retry_hint={"retryable": True, "suggested_action": "fix_sql", "reason_code": error_payload["code"]},
                next_handoff="validation_agent",
            )

        # 4. Post-execution self-check
        columns = preview_ref.preview.get("columns", [])
        row_count = int(preview_ref.preview.get("row_count", 0) or 0)
        post_checks = run_sql_self_check(
            sql_plan.generated_sql, columns=columns, row_count=row_count,
        )

        # 5. Register SQL plan artifact
        plan_ref = runtime.adapter.register_artifact(
            state.run_id,
            "file",
            content_text=json.dumps(sql_plan.model_dump(mode="json"), ensure_ascii=False, indent=2),
            filename=f"sql_plan_{state.run_id}.json",
            created_by_tool="DATA_Analyst_Assistant_Agent.sql_agent.planner",
            context=context,
            metadata={
                "kind": "sql_plan",
                "metric": sql_plan.metric,
                "dimension": sql_plan.dimension,
                "planner_mode": sql_plan.planner_mode,
            },
            preview={"metric": sql_plan.metric, "dimension": sql_plan.dimension, "planner_mode": sql_plan.planner_mode},
        )

        # 6. Register GE-style validation artifact
        ge_ref = runtime.adapter.register_ge_validation(
            state.run_id,
            table_name="sql_preview",
            source_ref=preview_ref,
            passed=all(c.passed for c in post_checks),
            row_count=row_count,
            schema_fingerprint="preview-columns:" + ",".join(columns),
            context=context,
        )

        # 7. Collect artifact refs
        artifact_refs = [preview_ref, plan_ref, ge_ref]
        flags: list[BusinessFlag] = []

        # 8. Mart candidate handling
        requires_mart = bool(plan and plan.requires_mart_review) or needs_mart_candidate(state.user_query)
        if requires_mart:
            candidate = build_mart_candidate(sql_plan, row_count=row_count, columns=columns)
            mart_artifact_id = register_mart_candidate_artifact(
                state, runtime, candidate, preview_ref.artifact_id,
            )
            state.mart_candidate_ids.append(mart_artifact_id)
            flags.append(
                BusinessFlag(
                    code="mart_candidate",
                    severity="info",
                    message="User query indicates repeatable analysis or mart storage intent.",
                )
            )

        return AgentEnvelope(
            status=AgentStatus.approval_required if requires_mart else AgentStatus.success,
            agent_name=self.name,
            summary="SQL preview completed.",
            artifact_refs=artifact_refs,
            validation=ValidationBlock(
                local_checks=post_checks,
                integrity_refs=[ge_ref],
                business_flags=flags,
            ),
            approval=ApprovalRequirement(
                required=requires_mart,
                reason="Reusable mart persistence requires user approval." if requires_mart else "",
                approval_type="mart_persistence" if requires_mart else "",
            ),
            context_refs=[{"kind": "run", "ref_id": state.run_id, "summary": "current run"}],
            next_handoff="validation_agent",
        )

    def _failed_envelope(self, checks: list[LocalCheck], sql_plan: SQLPlan) -> AgentEnvelope:
        return AgentEnvelope(
            status=AgentStatus.failed,
            agent_name=self.name,
            summary=f"SQL self-check failed: {[c.detail for c in checks if not c.passed]}",
            validation=ValidationBlock(local_checks=checks),
            retry_hint={"retryable": True, "suggested_action": "fix_sql", "reason_code": "self_check_failed"},
            next_handoff="validation_agent",
        )

    @staticmethod
    def _build_retry_error_payload(state: OrchestrationState, query: str, exc: Exception) -> dict[str, Any]:
        if isinstance(exc, BackendError):
            code = exc.code
            message = exc.message
        else:
            code = type(exc).__name__
            message = str(exc)
        return {
            "code": code or "preview_execution_failed",
            "message": message or "SQL preview failed.",
            "query": query,
            "datasource_id": state.datasource_id,
            "step": state.current_step or "sql_agent",
        }
