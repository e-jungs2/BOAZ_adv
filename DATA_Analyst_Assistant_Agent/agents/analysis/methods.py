from __future__ import annotations

from typing import Any

import pandas as pd

from DATA_Analyst_Assistant_Agent.models import OrchestrationState


def build_analysis_result(
    state: OrchestrationState,
    *,
    dataframe: pd.DataFrame | None = None,
    eda_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    plan = state.plan
    route_kind = state.route_kind or (plan.route_kind if plan else "simple")
    df = dataframe if dataframe is not None else pd.DataFrame()
    method_summary = "Descriptive summary over SQL result artifact data."
    if route_kind == "trend":
        method_summary = "Trend-oriented descriptive analysis over the SQL result artifact data."
    elif route_kind == "eda":
        method_summary = "Quality-aware descriptive analysis using the EDA profile artifact."
    elif route_kind == "comprehensive":
        method_summary = "Comprehensive descriptive analysis using SQL result data and EDA profile evidence."

    metric = plan.metric if plan else None
    dimension = plan.dimension if plan else None
    target = " and ".join(item for item in [dimension, metric] if item)
    finding_subject = target or "the requested SQL result"
    eda_profiles = eda_profiles or []
    has_eda = bool(state.artifact_ids.get("eda_agent"))

    key_findings = [
        f"{finding_subject} was analyzed using registered SQL result artifacts.",
    ]
    limitations = [
        "Findings are limited to the SQL result artifact rows available in this run.",
        "Findings describe observed structure only and do not claim causality.",
    ]
    data_quality_notes: list[str] = []

    if route_kind == "trend":
        key_findings.insert(0, "The trend route prepares evidence for directional review over the selected time dimension.")
    if has_eda:
        key_findings.append("EDA profile evidence was considered before producing the analysis summary.")
        limitations.append("EDA profile artifacts summarize data quality signals but do not replace full profiling.")
    for profile in eda_profiles:
        quality_status = profile.get("quality_status")
        if quality_status:
            data_quality_notes.append(f"EDA quality_status={quality_status}.")
        if quality_status and quality_status != "usable":
            limitations.append(f"EDA quality status is {quality_status}; review key issues before relying on findings.")
        data_quality_notes.extend(profile.get("key_issues", []) or [])

    if df.empty:
        key_findings.append("The SQL result artifact has no data rows available for metric calculations.")
        limitations.append("No row-level statistics could be computed from an empty SQL result artifact.")
    else:
        key_findings.extend(_data_findings(df, metric=metric, dimension=dimension))
        data_quality_notes.extend(_null_quality_notes(df))

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
        "data_quality_notes": data_quality_notes,
        "eda_profile_summaries": eda_profiles,
    }


def _data_findings(df: pd.DataFrame, *, metric: str | None, dimension: str | None) -> list[str]:
    findings = [f"SQL result contains {len(df)} rows and {len(df.columns)} columns."]
    numeric_cols = list(df.select_dtypes(include="number").columns)
    metric_col = metric if metric in df.columns else (numeric_cols[0] if numeric_cols else None)
    dimension_col = dimension if dimension in df.columns else _first_non_numeric_column(df, numeric_cols)

    if metric_col:
        series = df[metric_col].dropna()
        if not series.empty:
            findings.append(
                f"{metric_col} ranges from {series.min():g} to {series.max():g}, with mean {series.mean():.2f}."
            )
    if metric_col and dimension_col and dimension_col in df.columns:
        grouped = df.groupby(dimension_col, dropna=False)[metric_col].sum(numeric_only=True).sort_values(ascending=False)
        if not grouped.empty:
            top_key = str(grouped.index[0])
            findings.append(f"Top {dimension_col} by {metric_col} is {top_key} ({grouped.iloc[0]:g}).")
    elif dimension_col and dimension_col in df.columns:
        top = df[dimension_col].fillna("<NA>").astype(str).value_counts().head(1)
        if not top.empty:
            findings.append(f"Most frequent {dimension_col} value is {top.index[0]} ({int(top.iloc[0])} rows).")
    return findings


def _first_non_numeric_column(df: pd.DataFrame, numeric_cols: list[str]) -> str | None:
    for column in df.columns:
        if column not in numeric_cols:
            return column
    return None


def _null_quality_notes(df: pd.DataFrame) -> list[str]:
    notes: list[str] = []
    null_counts = df.isna().sum()
    for column, count in null_counts.items():
        if int(count) > 0:
            notes.append(f"{column} has {int(count)} null values.")
    return notes
