from __future__ import annotations

import json
from typing import Any

from data_agent_backend.models.artifacts import ArtifactType

from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime
from DATA_Analyst_Assistant_Agent.models import (
    AgentEnvelope,
    AgentStatus,
    BusinessFlag,
    LocalCheck,
    OrchestrationState,
    RetryHint,
    ValidationBlock,
)


class CentralValidationAgent:
    name = "validation_agent"

    def run(self, state: OrchestrationState, runtime: AgentRuntime, upstream: AgentEnvelope) -> AgentEnvelope:
        context = runtime.context(state, node_name=self.name, tool_name="validation_agent.business_context")
        findings: list[dict[str, Any]] = []
        verdict = "pass"
        status = AgentStatus.success
        approval = upstream.approval
        retry_hint = RetryHint()

        if upstream.validation.has_errors:
            verdict = "fail"
            status = AgentStatus.failed
            retry_hint = RetryHint(retryable=True, suggested_action="retry_upstream", reason_code="local_check_failed")
            findings.append({"category": "artifact_dependency_mismatch", "detail": "Upstream local check failed."})
        elif upstream.approval.required:
            verdict = "approval_required"
            status = AgentStatus.approval_required
            findings.append({"category": "approval_required_for_persistence", "detail": upstream.approval.reason})
        elif upstream.validation.has_warnings:
            verdict = "warn"
            status = AgentStatus.warning
            findings.append({"category": "business_context_warning", "detail": "Upstream result contains warnings."})
        else:
            findings.append({"category": "business_context_pass", "detail": "Upstream result can continue."})

        validation_ref = runtime.adapter.register_artifact(
            state.run_id,
            ArtifactType.file,
            content_text=json.dumps(
                {
                    "run_id": state.run_id,
                    "upstream_agent": upstream.agent_name,
                    "verdict": verdict,
                    "goal": state.goal,
                    "findings": findings,
                    "artifact_ids": upstream.artifact_ids(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            filename=f"central_validation_{upstream.agent_name}.json",
            created_by_tool="DATA_Analyst_Assistant_Agent.central_validation",
            context=context,
            parent_ids=upstream.artifact_ids(),
            lineage_edge_type="validates_business_context",
            metadata={"kind": "central_business_validation", "upstream_agent": upstream.agent_name, "verdict": verdict},
            preview={"verdict": verdict, "upstream_agent": upstream.agent_name, "finding_count": len(findings)},
        )

        return AgentEnvelope(
            status=status,
            agent_name=self.name,
            summary=f"Central validation verdict: {verdict}.",
            artifact_refs=[validation_ref],
            validation=ValidationBlock(
                local_checks=[
                    LocalCheck(
                        name="business_context_verdict",
                        passed=verdict in {"pass", "warn", "approval_required"},
                        severity="error" if verdict == "fail" else "info",
                        detail=verdict,
                    )
                ],
                business_flags=[
                    BusinessFlag(code=item["category"], severity="info" if verdict != "fail" else "error", message=item["detail"])
                    for item in findings
                ],
            ),
            retry_hint=retry_hint,
            approval=approval,
            context_refs=[{"kind": "upstream_agent", "ref_id": upstream.agent_name, "summary": upstream.summary}],
            next_handoff="supervisor_gate",
        )
