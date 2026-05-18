from __future__ import annotations

from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime
from DATA_Analyst_Assistant_Agent.agents.report.builder import build_report
from DATA_Analyst_Assistant_Agent.agents.report.self_check import run_report_self_check
from DATA_Analyst_Assistant_Agent.models import AgentEnvelope, OrchestrationState, ValidationBlock


class ReportAgent:
    name = "report_agent"

    def run(self, state: OrchestrationState, runtime: AgentRuntime) -> AgentEnvelope:
        context = runtime.context(state, node_name=self.name, tool_name="report_agent.final_report")
        parent_ids = [artifact_id for ids in state.artifact_ids.values() for artifact_id in ids]
        report = build_report(state)
        ref = runtime.adapter.save_workspace_file(
            state.run_id,
            report,
            context=context,
            filename="final_report.md",
            metadata={
                "kind": "final_report",
                "source_artifact_count": len(parent_ids),
                "source_artifact_ids": parent_ids,
            },
        )
        return AgentEnvelope(
            agent_name=self.name,
            summary="Final report generated from registered evidence artifacts.",
            artifact_refs=[ref],
            validation=ValidationBlock(local_checks=run_report_self_check(report)),
            next_handoff="validation_agent",
        )
