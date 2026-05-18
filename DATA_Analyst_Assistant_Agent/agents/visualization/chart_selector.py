from __future__ import annotations

from DATA_Analyst_Assistant_Agent.models import OrchestrationState


def select_chart_type(state: OrchestrationState) -> str:
    query = state.user_query.casefold()
    if any(token in query for token in ("monthly", "trend", "\uc6d4\ubcc4", "\ucd94\uc774")):
        return "line"
    if any(token in query for token in ("compare", "category", "top", "\ube44\uad50", "\uce74\ud14c\uace0\ub9ac")):
        return "bar"
    if any(token in query for token in ("distribution", "histogram", "\ubd84\ud3ec")):
        return "histogram"
    return "table"


def build_chart_config(state: OrchestrationState) -> dict:
    chart_type = select_chart_type(state)
    plan = state.plan
    x_field = plan.dimension if plan and plan.dimension else "dimension"
    y_field = plan.metric if plan and plan.metric else "metric"
    return {
        "chart_type": chart_type,
        "title": _title_for(chart_type, x_field, y_field),
        "encoding": {
            "x": {"field": x_field, "type": "temporal" if chart_type == "line" else "nominal", "label": x_field.title()},
            "y": {"field": y_field, "type": "quantitative", "label": y_field.title()},
        },
        "data_reference": state.artifact_ids.get("sql_agent", []),
        "analysis_reference": state.artifact_ids.get("analysis_agent", []),
    }


def _title_for(chart_type: str, x_field: str, y_field: str) -> str:
    if chart_type == "line":
        return f"{y_field.title()} trend by {x_field.title()}"
    if chart_type == "bar":
        return f"{y_field.title()} comparison by {x_field.title()}"
    if chart_type == "histogram":
        return f"{y_field.title()} distribution"
    return "SQL result preview"
