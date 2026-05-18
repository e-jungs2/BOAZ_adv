from __future__ import annotations

import json

from data_agent_backend.models.artifacts import ArtifactType

from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime
from DATA_Analyst_Assistant_Agent.models import AgentEnvelope, LocalCheck, OrchestrationState, ValidationBlock


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
            created_by_tool="DATA_Analyst_Assistant_Agent.eda",
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
