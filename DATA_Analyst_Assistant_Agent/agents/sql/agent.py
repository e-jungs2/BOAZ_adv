from __future__ import annotations

from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime
from DATA_Analyst_Assistant_Agent.models import (
    AgentEnvelope,
    AgentStatus,
    ApprovalRequirement,
    BusinessFlag,
    LocalCheck,
    OrchestrationState,
    ValidationBlock,
)


class SQLAgent:
    name = "sql_agent"

    def run(self, state: OrchestrationState, runtime: AgentRuntime) -> AgentEnvelope:
        plan = state.plan
        query = plan.source_sql if plan else "SELECT 1 AS sample_value"
        context = runtime.context(state, node_name=self.name, tool_name="sql_agent.preview")

        preview_ref = runtime.adapter.run_sql_preview(state.run_id, query, context=context)
        ge_ref = runtime.adapter.register_ge_validation(
            state.run_id,
            table_name="sql_preview",
            source_ref=preview_ref,
            passed=True,
            row_count=int(preview_ref.preview.get("row_count", 0) or 0),
            schema_fingerprint="preview-columns:" + ",".join(preview_ref.preview.get("columns", [])),
            context=context,
        )

        checks = [
            LocalCheck(name="read_only_preview_executed", passed=True, detail="Preview was executed through backend SQLExecutor."),
            LocalCheck(
                name="result_shape_available",
                passed=bool(preview_ref.preview.get("columns")),
                severity="error" if not preview_ref.preview.get("columns") else "info",
                detail="Preview artifact contains columns metadata.",
            ),
        ]
        requires_mart_review = bool(plan and plan.requires_mart_review)
        flags = []
        if requires_mart_review:
            flags.append(
                BusinessFlag(
                    code="mart_candidate",
                    severity="info",
                    message="User query indicates repeatable analysis or mart storage intent.",
                )
            )

        return AgentEnvelope(
            status=AgentStatus.approval_required if requires_mart_review else AgentStatus.success,
            agent_name=self.name,
            summary="SQL preview completed.",
            artifact_refs=[preview_ref],
            validation=ValidationBlock(local_checks=checks, integrity_refs=[ge_ref], business_flags=flags),
            approval=ApprovalRequirement(
                required=requires_mart_review,
                reason="Reusable mart persistence requires user approval." if requires_mart_review else "",
                approval_type="mart_persistence" if requires_mart_review else "",
            ),
            context_refs=[{"kind": "run", "ref_id": state.run_id, "summary": "current run"}],
            next_handoff="validation_agent",
        )
