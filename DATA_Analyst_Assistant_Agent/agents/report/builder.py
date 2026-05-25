from __future__ import annotations

from typing import Any

from DATA_Analyst_Assistant_Agent.models import OrchestrationState


def build_report(
    state: OrchestrationState,
    *,
    generated_sql: str = "",
    eda_profile: dict[str, Any] | None = None,
    analysis_result: dict[str, Any] | None = None,
    visualization_result: dict[str, Any] | None = None,
) -> str:
    evidence_lines = _evidence_lines(state)
    visual_lines = _visual_lines(state, visualization_result)
    finding_lines = _finding_lines(analysis_result)
    eda_lines = _eda_lines(eda_profile)
    return "\n".join(
        [
            f"# Data Analyst Assistant Report: {state.goal or state.user_query}",
            "",
            "## User Question",
            state.user_query,
            "",
            "## Generated SQL",
            "```sql",
            generated_sql or "SQL was not captured for this run.",
            "```",
            "",
            "## Summary",
            _summary_for_route(state),
            "",
            "## EDA Summary",
            *eda_lines,
            "",
            "## Key Findings",
            *finding_lines,
            "",
            "## Visuals",
            *visual_lines,
            "",
            "## Evidence",
            *evidence_lines,
            "",
            "## Limitations",
            *_limitation_lines(analysis_result),
            "",
            "## Next Actions",
            "- Review upstream artifacts for evidence details.",
            "- Refine SQL or route selection if validation reports retryable data quality issues.",
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


def _eda_lines(profile: dict[str, Any] | None) -> list[str]:
    if not profile:
        return ["- EDA profile artifact was not generated for this route."]
    return [
        f"- Row count: {profile.get('row_count', 0)}",
        f"- Columns: {', '.join(profile.get('columns', []) or []) or 'none'}",
        f"- Quality status: {profile.get('quality_status', 'unknown')}",
        f"- Key issues: {'; '.join(profile.get('key_issues', []) or []) or 'none'}",
    ]


def _finding_lines(result: dict[str, Any] | None) -> list[str]:
    if not result:
        return ["- Analysis artifact was not requested for this route."]
    findings = result.get("key_findings", []) or []
    return [f"- {finding}" for finding in findings] or ["- No findings were generated."]


def _visual_lines(state: OrchestrationState, visualization: dict[str, Any] | None) -> list[str]:
    refs = state.artifact_ids.get("visualization_agent", [])
    if not refs:
        return ["- No visualization artifact generated."]
    chart_type = (visualization or {}).get("chart_type", "unknown")
    lines = [f"- Visualization artifact: {artifact_id}" for artifact_id in refs]
    lines.append(f"- Chart type: {chart_type}")
    return lines


def _limitation_lines(result: dict[str, Any] | None) -> list[str]:
    limitations = (result or {}).get("limitations", []) or [
        "Findings are limited to the SQL result artifacts available in this run.",
        "Findings are descriptive and should not be interpreted as causal claims.",
    ]
    return [f"- {limitation}" for limitation in limitations]
