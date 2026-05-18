from __future__ import annotations

from DATA_Analyst_Assistant_Agent.models import OrchestrationState


def build_analysis_result(state: OrchestrationState) -> dict:
    plan = state.plan
    route_kind = state.route_kind or (plan.route_kind if plan else "simple")
    method_summary = "Descriptive summary over SQL preview artifacts."
    if route_kind == "trend":
        method_summary = "Trend-oriented descriptive analysis over the available SQL preview."
    elif route_kind == "eda":
        method_summary = "Quality-aware descriptive analysis using the EDA profile artifact."

    metric = plan.metric if plan else None
    dimension = plan.dimension if plan else None
    target = " and ".join(item for item in [dimension, metric] if item)
    finding_subject = target or "the requested SQL result"

    return {
        "run_id": state.run_id,
        "goal": state.goal,
        "method_summary": method_summary,
        "key_findings": [
            f"{finding_subject} can be reviewed using the registered SQL evidence artifacts.",
            "Current MVP findings are descriptive and should be validated with full result data before business action.",
        ],
        "limitations": [
            "This MVP analysis uses artifact previews, not full raw datasets.",
            "Findings describe observed structure only and do not claim causality.",
        ],
        "source_artifacts": {
            "sql": state.artifact_ids.get("sql_agent", []),
            "eda": state.artifact_ids.get("eda_agent", []),
        },
    }
