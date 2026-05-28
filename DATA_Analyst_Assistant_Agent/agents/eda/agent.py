from __future__ import annotations

import json
from typing import Any

from data_agent_backend.models.artifacts import ArtifactType

from DATA_Analyst_Assistant_Agent.agents.artifact_data import read_sql_result_csvs
from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime
from DATA_Analyst_Assistant_Agent.agents.eda.profiler import profile_from_csv_artifacts
from DATA_Analyst_Assistant_Agent.agents.eda.self_check import run_eda_self_check
from DATA_Analyst_Assistant_Agent.models import AgentEnvelope, OrchestrationState, ValidationBlock


class EDAAgent:
    name = "eda_agent"

    def run(self, state: OrchestrationState, runtime: AgentRuntime) -> AgentEnvelope:
        context = runtime.context(state, node_name=self.name, tool_name="eda_agent.profile")
        csvs = read_sql_result_csvs(state, runtime)
        source_ids = [csv.artifact_id for csv in csvs]
        profile = profile_from_csv_artifacts(csvs)
        main_eda_result = self._run_main_eda_logic(csvs, state)
        payload = {
            "run_id": state.run_id,
            "source_artifacts": source_ids,
            "profile": profile,
            "main_eda_agent": main_eda_result,
        }
        ref = runtime.adapter.register_artifact(
            state.run_id,
            ArtifactType.data_profile,
            content_text=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
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
                "recommended_next_steps": profile["recommended_next_steps"],
            },
        )
        return AgentEnvelope(
            agent_name=self.name,
            summary="EDA profile generated from SQL result CSV artifacts.",
            artifact_refs=[ref],
            validation=ValidationBlock(local_checks=run_eda_self_check(source_ids, profile)),
            next_handoff="validation_agent",
        )

    def _run_main_eda_logic(self, csvs: list[Any], state: OrchestrationState) -> dict[str, Any]:
        """Use the EDA implementation copied from main/eda_agent on orchestration CSV output."""
        frames = [csv.dataframe for csv in csvs if csv.error is None and not csv.dataframe.empty]
        if not frames:
            raise RuntimeError("No non-empty SQL CSV artifact was available for EDA.")

        import pandas as pd

        from eda_agent.skills.comparison_skill import run_comparison_skill
        from eda_agent.skills.data_quality_skill import run_data_quality_skill
        from eda_agent.skills.distribution_skill import run_distribution_skill
        from eda_agent.skills.relationship_skill import run_relationship_skill
        from eda_agent.skills.time_skill import run_time_skill
        from eda_agent.tools.profiling import get_basic_profile

        df = pd.concat(frames, ignore_index=True)
        numeric_cols = list(df.select_dtypes(include=["number"]).columns)
        categorical_cols = list(df.select_dtypes(exclude=["number"]).columns)
        key_col = categorical_cols[0] if categorical_cols else None
        measure_cols = numeric_cols or None
        time_cols = [col for col in df.columns if "datetime" in str(df[col].dtype) or "date" in col.lower()]

        result: dict[str, Any] = {
            "status": "success",
            "question_type": state.route_kind,
            "basic_profile": get_basic_profile(df),
            "quality_result": run_data_quality_skill(df, key_col=key_col, measure_cols=measure_cols),
            "selected_columns": {
                "key_col": key_col,
                "measure_cols": measure_cols or [],
                "time_cols": time_cols,
            },
        }
        result["distribution_result"] = run_distribution_skill(
            df,
            measure_cols=measure_cols,
            question_type=state.route_kind,
        )
        result["comparison_result"] = run_comparison_skill(
            df,
            key_col=key_col,
            measure_cols=measure_cols,
            question_type=state.route_kind,
        )
        result["relationship_result"] = run_relationship_skill(
            df,
            measure_cols=measure_cols,
            question_type=state.route_kind,
        )
        result["time_result"] = run_time_skill(df, measure_cols=measure_cols, time_cols=time_cols)

        return result
