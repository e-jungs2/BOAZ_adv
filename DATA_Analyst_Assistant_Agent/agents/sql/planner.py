"""SQL plan generation for the SQL-Agent.

MVP: deterministic keyword-based plan. Structured so real schema/catalog
lookup or LLM-based generation can be inserted later.
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
    """Build a deterministic SQL plan from the user query and optional analysis plan.

    MVP: no schema lookup, no LLM. Returns a structured plan with fallback SQL.
    Replace _build_fallback_sql() with real catalog-driven generation later.
    """
    metric = _detect_metric(user_query)
    dimension = _detect_dimension(user_query)

    # Use analysis_plan hints if available
    if analysis_plan:
        metric = metric or analysis_plan.metric
        dimension = dimension or analysis_plan.dimension

    sql = _build_fallback_sql(metric, dimension)
    selected_columns = _infer_columns(metric, dimension)

    return SQLPlan(
        selected_tables=["source_table"],
        selected_columns=selected_columns,
        metric=metric,
        dimension=dimension,
        filters=[],
        generated_sql=sql,
        reasoning=_build_reasoning(metric, dimension),
    )


def _build_fallback_sql(metric: str | None, dimension: str | None) -> str:
    """Generate deterministic fallback SQL based on detected metric/dimension.

    MVP: always produces a self-contained SELECT that does not require real tables.
    This is the extension point: replace with real schema-aware SQL generation
    once catalog/schema lookup is connected.
    """
    if metric and dimension:
        return f"SELECT 1 AS {dimension}, 1 AS {metric}"
    if metric:
        return f"SELECT 1 AS {metric}"
    if dimension:
        return f"SELECT 1 AS {dimension}"
    return "SELECT 1 AS sample_value"


def _infer_columns(metric: str | None, dimension: str | None) -> list[str]:
    cols: list[str] = []
    if dimension == "month":
        cols.append("month")
    elif dimension == "day":
        cols.append("day")
    if metric == "revenue":
        cols.append("revenue")
    elif metric == "order_count":
        cols.append("order_count")
    return cols or ["sample_value"]


def _build_reasoning(metric: str | None, dimension: str | None) -> str:
    parts: list[str] = []
    if metric:
        parts.append(f"metric={metric}")
    if dimension:
        parts.append(f"dimension={dimension}")
    if parts:
        return f"Deterministic MVP plan: {', '.join(parts)}."
    return "Deterministic MVP fallback: no specific metric or dimension detected."
