from __future__ import annotations

import json

from data_agent_backend.models.artifacts import ArtifactType

from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime
from DATA_Analyst_Assistant_Agent.models import AgentEnvelope, LocalCheck, OrchestrationState, ValidationBlock


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
            created_by_tool="DATA_Analyst_Assistant_Agent.visualization",
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
