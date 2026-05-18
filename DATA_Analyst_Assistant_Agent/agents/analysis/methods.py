from __future__ import annotations

from DATA_Analyst_Assistant_Agent.models import OrchestrationState


def build_analysis_result(state: OrchestrationState, eda_profiles: list[dict] | None = None) -> dict:
    plan = state.plan
    route_kind = state.route_kind or (plan.route_kind if plan else "simple")
    method_summary = "Descriptive summary over SQL preview artifacts."
    if route_kind == "trend":
        method_summary = "Trend-oriented descriptive analysis over the available SQL preview."
    elif route_kind == "eda":
        method_summary = "Quality-aware descriptive analysis using the EDA profile artifact."
    elif route_kind == "comprehensive":
        method_summary = "Comprehensive descriptive analysis using SQL preview artifacts and EDA profile evidence."

    metric = plan.metric if plan else None
    dimension = plan.dimension if plan else None
    target = " and ".join(item for item in [dimension, metric] if item)
    finding_subject = target or "the requested SQL result"
    eda_profiles = eda_profiles or []
    has_eda = bool(state.artifact_ids.get("eda_agent"))

    key_findings = [
        f"{finding_subject} can be reviewed using the registered SQL evidence artifacts.",
        "Current MVP findings are descriptive and should be validated with full result data before business action.",
    ]
    limitations = [
        "This MVP analysis uses artifact previews, not full raw datasets.",
        "Findings describe observed structure only and do not claim causality.",
    ]

    if route_kind == "trend":
        key_findings.insert(0, "The trend route prepares evidence for directional review over the selected time dimension.")
    if has_eda:
        key_findings.append("EDA profile evidence was considered before producing the analysis summary.")
        limitations.append("EDA profile artifacts summarize data quality signals but do not replace full profiling.")
    for profile in eda_profiles:
        quality_status = profile.get("quality_status")
        if quality_status and quality_status != "usable":
            limitations.append(f"EDA quality status is {quality_status}; review key issues before relying on findings.")

    return {
        "run_id": state.run_id,
        "goal": state.goal,
        "method_summary": method_summary,
        "key_findings": key_findings,
        "limitations": limitations,
        "source_artifacts": {
            "sql": state.artifact_ids.get("sql_agent", []),
            "eda": state.artifact_ids.get("eda_agent", []),
        },
        "eda_profile_summaries": eda_profiles,
    }
