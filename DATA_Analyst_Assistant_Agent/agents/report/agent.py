from __future__ import annotations

from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime
from DATA_Analyst_Assistant_Agent.models import AgentEnvelope, LocalCheck, OrchestrationState, ValidationBlock


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
