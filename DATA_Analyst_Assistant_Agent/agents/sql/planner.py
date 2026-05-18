"""SQL plan generation for the SQL-Agent.

Deterministic keyword-based plan with route-aware SQL templates.
Structured so real schema/catalog lookup or LLM-based generation can be inserted later.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from DATA_Analyst_Assistant_Agent.models import AnalysisPlan


class SQLPlan(BaseModel):
    """Structured SQL plan produced by the planner."""
    selected_tables: list[str] = Field(default_factory=list)
    selected_columns: list[str] = Field(default_factory=list)
    metric: str | None = None
    dimension: str | None = None
    filters: list[str] = Field(default_factory=list)
    generated_sql: str = "SELECT 1 AS sample_value"
    reasoning: str = ""
    route_kind: str = "simple"


def _detect_metric(query: str) -> str | None:
    query_lower = query.lower()
    if any(kw in query for kw in ("매출", "수익")) or any(kw in query_lower for kw in ("revenue", "sales")):
        return "revenue"
    if any(kw in query for kw in ("주문", "건수")) or "order" in query_lower:
        return "order_count"
    return None


def _detect_dimension(query: str) -> str | None:
    query_lower = query.lower()
    if any(kw in query for kw in ("월별", "추이")) or any(kw in query_lower for kw in ("monthly", "trend")):
        return "month"
    if any(kw in query for kw in ("일별",)) or "daily" in query_lower:
        return "day"
    return None


def build_sql_plan(user_query: str, analysis_plan: AnalysisPlan | None = None) -> SQLPlan:
    """Build a deterministic SQL plan from the user query and optional analysis plan."""
    metric = _detect_metric(user_query)
    dimension = _detect_dimension(user_query)
    route_kind = analysis_plan.route_kind if analysis_plan else "simple"

    # Use analysis_plan hints if available
    if analysis_plan:
        metric = metric or analysis_plan.metric
        dimension = dimension or analysis_plan.dimension

    sql = _build_template_sql(route_kind, metric, dimension)
    selected_columns = _infer_columns(metric, dimension, route_kind)

    return SQLPlan(
        selected_tables=["source_table"],
        selected_columns=selected_columns,
        metric=metric,
        dimension=dimension,
        filters=[],
        generated_sql=sql,
        reasoning=_build_reasoning(route_kind, metric, dimension),
        route_kind=route_kind,
    )


# ── Route-aware SQL templates ──

_TEMPLATES: dict[str, str] = {
    "simple_metric": "SELECT 1 AS {metric}",
    "simple_dimension_metric": "SELECT 1 AS {dimension}, 1 AS {metric}",
    "trend": (
        "WITH monthly_data AS ("
        "  SELECT 1 AS {dimension}, 1 AS {metric}"
        ") "
        "SELECT {dimension}, {metric} FROM monthly_data ORDER BY {dimension}"
    ),
    "eda": (
        "SELECT 1 AS column_name, 1 AS non_null_count, 1 AS distinct_count, "
        "1 AS sample_value"
    ),
    "comprehensive": (
        "WITH base_data AS ("
        "  SELECT 1 AS {dimension}, 1 AS {metric}"
        ") "
        "SELECT {dimension}, {metric} FROM base_data ORDER BY {dimension}"
    ),
    "fallback": "SELECT 1 AS sample_value",
}


def _build_template_sql(route_kind: str, metric: str | None, dimension: str | None) -> str:
    """Select and fill a SQL template based on route_kind and detected fields.

    MVP: all templates produce self-contained SELECTs that need no real tables.
    Extension point: replace with real schema-aware SQL generation.
    """
    m = metric or "value"
    d = dimension or "category"

    if route_kind == "trend":
        return _TEMPLATES["trend"].format(metric=m, dimension=d)
    if route_kind == "eda":
        return _TEMPLATES["eda"]
    if route_kind == "comprehensive":
        return _TEMPLATES["comprehensive"].format(metric=m, dimension=d)
    # simple / mart / unknown
    if metric and dimension:
        return _TEMPLATES["simple_dimension_metric"].format(metric=m, dimension=d)
    if metric:
        return _TEMPLATES["simple_metric"].format(metric=m)
    return _TEMPLATES["fallback"]


def _infer_columns(metric: str | None, dimension: str | None, route_kind: str) -> list[str]:
    if route_kind == "eda":
        return ["column_name", "non_null_count", "distinct_count", "sample_value"]
    cols: list[str] = []
    if dimension:
        cols.append(dimension)
    if metric:
        cols.append(metric)
    return cols or ["sample_value"]


def _build_reasoning(route_kind: str, metric: str | None, dimension: str | None) -> str:
    parts = [f"route={route_kind}"]
    if metric:
        parts.append(f"metric={metric}")
    if dimension:
        parts.append(f"dimension={dimension}")
    return f"Deterministic plan: {', '.join(parts)}."
