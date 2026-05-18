from __future__ import annotations

from DATA_Analyst_Assistant_Agent.models import OrchestrationState


def build_report(state: OrchestrationState) -> str:
    evidence_lines = _evidence_lines(state)
    visual_lines = [f"- {artifact_id}" for artifact_id in state.artifact_ids.get("visualization_agent", [])] or ["- No chart artifact generated."]
    finding_lines = [f"- {artifact_id}" for artifact_id in state.artifact_ids.get("analysis_agent", [])] or [
        "- Analysis artifact was not requested for this route."
    ]
    return "\n".join(
        [
            f"# Data Analyst Assistant Report: {state.goal or state.user_query}",
            "",
            "## Summary",
            _summary_for_route(state),
            "",
            "## Key Findings",
            *finding_lines,
            "",
            "## Evidence",
            *evidence_lines,
            "",
            "## Visuals",
            *visual_lines,
            "",
            "## Limitations",
            "- This MVP report summarizes artifact previews and registered metadata, not full raw datasets.",
            "- Findings are descriptive and should not be interpreted as causal claims.",
            "",
            "## Next Actions",
            "- Review upstream artifacts for evidence details.",
            "- Add full SQL, EDA, or visualization implementations as the route matures.",
        ]
    )


def _evidence_lines(state: OrchestrationState) -> list[str]:
    lines: list[str] = []
    for agent_name, artifact_ids in sorted(state.artifact_ids.items()):
        if agent_name == "report_agent":
            continue
        for artifact_id in artifact_ids:
            lines.append(f"- {agent_name}: {artifact_id}")
    return lines or ["- No evidence artifacts were registered."]


def _summary_for_route(state: OrchestrationState) -> str:
    route_kind = state.route_kind
    if route_kind == "eda":
        return "The assistant produced a data profile and quality summary from registered SQL evidence artifacts."
    if route_kind == "trend":
        return "The assistant produced descriptive trend analysis and a chart configuration from registered artifacts."
    if route_kind == "comprehensive":
        return "The assistant combined EDA, descriptive analysis, and visualization artifacts into one evidence-backed report."
    if route_kind == "mart":
        return "The assistant identified reusable mart intent; durable persistence remains approval-gated."
    return "The assistant completed a SQL-based response using registered backend artifacts."
