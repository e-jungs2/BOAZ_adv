from __future__ import annotations

import json

from data_agent_backend.models.artifacts import ArtifactType

from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime
from DATA_Analyst_Assistant_Agent.agents.eda.profiler import profile_from_artifacts
from DATA_Analyst_Assistant_Agent.agents.eda.self_check import run_eda_self_check
from DATA_Analyst_Assistant_Agent.models import AgentEnvelope, OrchestrationState, ValidationBlock


class EDAAgent:
    name = "eda_agent"

    def run(self, state: OrchestrationState, runtime: AgentRuntime) -> AgentEnvelope:
        context = runtime.context(state, node_name=self.name, tool_name="eda_agent.profile")
        source_ids = state.artifact_ids.get("sql_agent", [])
        source_artifacts = [runtime.adapter.get_artifact(artifact_id) for artifact_id in source_ids]
        profile = profile_from_artifacts(source_artifacts)
        payload = {
            "run_id": state.run_id,
            "source_artifacts": source_ids,
            "profile": profile,
        }
        ref = runtime.adapter.register_artifact(
            state.run_id,
            ArtifactType.data_profile,
            content_text=json.dumps(payload, ensure_ascii=False, indent=2),
            filename="eda_summary.json",
            created_by_tool="DATA_Analyst_Assistant_Agent.eda",
            context=context,
            parent_ids=source_ids,
            metadata={"kind": "eda_summary", "source_artifact_count": len(source_ids)},
            preview={
                "row_count": profile["row_count"],
                "columns": profile["columns"],
                "sample_available": profile["sample_available"],
                "quality_status": profile["quality_status"],
                "key_issues": profile["key_issues"],
            },
        )
        return AgentEnvelope(
            agent_name=self.name,
            summary="EDA profile generated from SQL artifact previews.",
            artifact_refs=[ref],
            validation=ValidationBlock(local_checks=run_eda_self_check(source_ids, profile)),
            next_handoff="validation_agent",
        )
