from __future__ import annotations

import json

from data_agent_backend.models.artifacts import ArtifactType

from DATA_Analyst_Assistant_Agent.agents.analysis.methods import build_analysis_result
from DATA_Analyst_Assistant_Agent.agents.analysis.self_check import run_analysis_self_check
from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime
from DATA_Analyst_Assistant_Agent.models import AgentEnvelope, OrchestrationState, ValidationBlock


class AnalysisAgent:
    name = "analysis_agent"

    def run(self, state: OrchestrationState, runtime: AgentRuntime) -> AgentEnvelope:
        context = runtime.context(state, node_name=self.name, tool_name="analysis_agent.result")
        parent_ids = state.artifact_ids.get("eda_agent", []) + state.artifact_ids.get("sql_agent", [])
        eda_profiles = [runtime.adapter.get_artifact(artifact_id).preview or {} for artifact_id in state.artifact_ids.get("eda_agent", [])]
        result = build_analysis_result(state, eda_profiles=eda_profiles)
        ref = runtime.adapter.register_artifact(
            state.run_id,
            ArtifactType.file,
            content_text=json.dumps(result, ensure_ascii=False, indent=2),
            filename="analysis_result.json",
            created_by_tool="DATA_Analyst_Assistant_Agent.analysis",
            context=context,
            parent_ids=parent_ids,
            metadata={"kind": "analysis_result", "source_artifact_count": len(parent_ids)},
            preview={
                "method_summary": result["method_summary"],
                "key_findings": result["key_findings"],
                "limitations": result["limitations"],
            },
        )
        return AgentEnvelope(
            agent_name=self.name,
            summary="Analysis result generated from registered evidence artifacts.",
            artifact_refs=[ref],
            validation=ValidationBlock(local_checks=run_analysis_self_check(result)),
            next_handoff="validation_agent",
        )
