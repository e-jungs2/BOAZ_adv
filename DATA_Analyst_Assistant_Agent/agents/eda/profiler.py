from __future__ import annotations

from data_agent_backend.models.artifacts import ArtifactRecord


def profile_from_artifacts(artifacts: list[ArtifactRecord]) -> dict:
    columns: list[str] = []
    row_count = 0
    sample_available = False
    key_issues: list[str] = []

    if not artifacts:
        key_issues.append("No SQL result artifact was available for EDA.")

    for artifact in artifacts:
        preview = artifact.preview or {}
        for column in preview.get("columns", []) or []:
            if column not in columns:
                columns.append(column)
        row_count = max(row_count, int(preview.get("row_count", 0) or 0))
        sample_available = sample_available or bool(preview.get("sample_rows"))

    if artifacts and not columns:
        key_issues.append("SQL result preview did not include column metadata.")
    if artifacts and row_count == 0:
        key_issues.append("SQL result preview reported zero rows.")

    return {
        "row_count": row_count,
        "columns": columns,
        "sample_available": sample_available,
        "quality_status": "needs_review" if key_issues else "usable",
        "key_issues": key_issues,
        "recommended_next_steps": ["analysis"] if columns else ["clarify_data_source"],
    }
