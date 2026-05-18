from __future__ import annotations

import json

from data_agent_backend.models.artifacts import ArtifactType

from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime
from DATA_Analyst_Assistant_Agent.models import AgentEnvelope, LocalCheck, OrchestrationState, ValidationBlock


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
            created_by_tool="DATA_Analyst_Assistant_Agent.analysis",
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
