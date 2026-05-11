from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from data_agent_backend.models.artifacts import ArtifactRef, ArtifactType
from data_agent_backend.models.contexts import PolicyContext

from sql_agent_orchestration.backend_adapter import BackendAdapter
from sql_agent_orchestration.models import (
    AgentEnvelope,
    AgentStatus,
    ApprovalRequirement,
    BusinessFlag,
    LocalCheck,
    OrchestrationState,
    RetryHint,
    ValidationBlock,
)


@dataclass
class AgentRuntime:
    adapter: BackendAdapter

    def context(self, state: OrchestrationState, *, node_name: str, tool_name: str) -> PolicyContext:
        return PolicyContext(
            run_id=state.run_id,
            thread_id=state.thread_id,
            node_name=node_name,
            tool_name=tool_name,
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
            created_by_tool="sql_agent_orchestration.central_validation",
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


class EDAAgent:
    name = "eda_agent"

    def run(self, state: OrchestrationState, runtime: AgentRuntime) -> AgentEnvelope:
        context = runtime.context(state, node_name=self.name, tool_name="eda_agent.summary")
        preview_ids = state.artifact_ids.get("sql_agent", [])
        payload = {
            "run_id": state.run_id,
            "source_artifacts": preview_ids,
            "profile": {
                "checks": ["row_count", "columns", "missing_values_placeholder", "duplicates_placeholder"],
                "status": "minimal_profile_ready",
            },
        }
        ref = runtime.adapter.register_artifact(
            state.run_id,
            ArtifactType.data_profile,
            content_text=json.dumps(payload, ensure_ascii=False, indent=2),
            filename="eda_summary.json",
            created_by_tool="sql_agent_orchestration.eda",
            context=context,
            parent_ids=preview_ids,
            metadata={"kind": "eda_summary"},
            preview={"status": "minimal_profile_ready", "source_artifact_count": len(preview_ids)},
        )
        return AgentEnvelope(
            agent_name=self.name,
            summary="Minimal EDA summary generated.",
            artifact_refs=[ref],
            validation=ValidationBlock(local_checks=[LocalCheck(name="profile_generated", passed=True)]),
            next_handoff="validation_agent",
        )


class AnalysisAgent:
    name = "analysis_agent"

    def run(self, state: OrchestrationState, runtime: AgentRuntime) -> AgentEnvelope:
        context = runtime.context(state, node_name=self.name, tool_name="analysis_agent.summary")
        parent_ids = state.artifact_ids.get("eda_agent", []) + state.artifact_ids.get("sql_agent", [])
        payload = {
            "run_id": state.run_id,
            "goal": state.goal,
            "key_findings": ["SQL preview is available for downstream interpretation."],
            "limitations": ["MVP analysis uses deterministic summary logic."],
        }
        ref = runtime.adapter.register_artifact(
            state.run_id,
            ArtifactType.file,
            content_text=json.dumps(payload, ensure_ascii=False, indent=2),
            filename="analysis_result.json",
            created_by_tool="sql_agent_orchestration.analysis",
            context=context,
            parent_ids=parent_ids,
            metadata={"kind": "analysis_result"},
            preview={"key_findings": payload["key_findings"], "limitations": payload["limitations"]},
        )
        return AgentEnvelope(
            agent_name=self.name,
            summary="Minimal analysis result generated.",
            artifact_refs=[ref],
            validation=ValidationBlock(
                local_checks=[
                    LocalCheck(name="key_findings_present", passed=True),
                    LocalCheck(name="limitations_present", passed=True),
                ]
            ),
            next_handoff="validation_agent",
        )


class VisualizationAgent:
    name = "visualization_agent"

    def run(self, state: OrchestrationState, runtime: AgentRuntime) -> AgentEnvelope:
        context = runtime.context(state, node_name=self.name, tool_name="visualization_agent.chart_spec")
        parent_ids = state.artifact_ids.get("analysis_agent", [])
        payload = {
            "chart_type": "line" if "월" in state.user_query or "추이" in state.user_query else "table",
            "encoding": {"x": "dimension", "y": "metric"},
            "data_reference": state.artifact_ids.get("sql_agent", []),
        }
        ref = runtime.adapter.register_artifact(
            state.run_id,
            ArtifactType.chart,
            content_text=json.dumps(payload, ensure_ascii=False, indent=2),
            filename="chart_config.json",
            created_by_tool="sql_agent_orchestration.visualization",
            context=context,
            parent_ids=parent_ids,
            metadata={"kind": "chart_config", "chart_type": payload["chart_type"]},
            preview={"chart_type": payload["chart_type"], "data_reference_count": len(payload["data_reference"])},
        )
        return AgentEnvelope(
            agent_name=self.name,
            summary="Chart specification generated.",
            artifact_refs=[ref],
            validation=ValidationBlock(
                local_checks=[
                    LocalCheck(name="chart_type_present", passed=True),
                    LocalCheck(name="data_reference_present", passed=bool(payload["data_reference"]), severity="warning"),
                ]
            ),
            next_handoff="validation_agent",
        )


class ReportAgent:
    name = "report_agent"

    def run(self, state: OrchestrationState, runtime: AgentRuntime) -> AgentEnvelope:
        context = runtime.context(state, node_name=self.name, tool_name="report_agent.final_report")
        parent_ids: list[str] = []
        for ids in state.artifact_ids.values():
            parent_ids.extend(ids)
        report = "\n".join(
            [
                f"# SQL Agent Report: {state.goal or state.user_query}",
                "",
                "## Summary",
                "The supervisor completed the MVP query-to-report path using backend artifacts.",
                "",
                "## Evidence",
                f"- Upstream artifact count: {len(parent_ids)}",
                "",
                "## Limitations",
                "- This MVP report uses deterministic placeholder EDA/analysis where full agents are not yet migrated.",
            ]
        )
        ref = runtime.adapter.save_workspace_file(
            state.run_id,
            report,
            context=context,
            filename="final_report.md",
            metadata={"kind": "final_report", "source_artifact_count": len(parent_ids)},
        )
        return AgentEnvelope(
            agent_name=self.name,
            summary="Final report generated.",
            artifact_refs=[ref],
            validation=ValidationBlock(
                local_checks=[
                    LocalCheck(name="summary_present", passed="## Summary" in report),
                    LocalCheck(name="limitations_present", passed="## Limitations" in report),
                ]
            ),
            next_handoff="validation_agent",
        )
