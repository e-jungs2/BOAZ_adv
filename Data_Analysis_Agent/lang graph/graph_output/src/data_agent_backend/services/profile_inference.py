from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from data_agent_backend.models.analysis_context import ColumnProfile, JoinPath, MartDefinition, TableProfile
from data_agent_backend.models.common import utc_now_iso
from data_agent_backend.models.datasources import DatasourceCatalogColumn


@dataclass(frozen=True)
class InferredTableProfile:
    table_profile: TableProfile
    column_profiles: list[ColumnProfile]
    join_paths: list[JoinPath]
    marts: list[MartDefinition]


class ProfileInferenceEngine:
    version = 1

    def infer_table(
        self,
        datasource_id: str,
        schema_name: str | None,
        table_name: str,
        columns: list[DatasourceCatalogColumn],
        sample_rows: list[dict[str, Any]],
        sample_limit: int,
        row_count: int | None = None,
    ) -> InferredTableProfile:
        profiled_at = utc_now_iso()
        column_profiles = [
            self._column_profile(datasource_id, schema_name, table_name, column, sample_rows, sample_limit, profiled_at)
            for column in columns
        ]
        primary_date_column = self._primary_date_column(column_profiles)
        table_type = self._table_type(table_name)
        table_profile = TableProfile(
            datasource_id=datasource_id,
            schema_name=schema_name,
            table_name=table_name,
            row_count=row_count,
            table_type=table_type,
            primary_date_column=primary_date_column,
            metadata=self._metadata(
                sample_limit,
                profiled_at,
                {
                    "row_count": "catalog" if row_count is not None else "inferred",
                    "table_type": "inferred",
                    "primary_date_column": "inferred" if primary_date_column else "catalog",
                },
                [f"table_type inferred as {table_type}"],
            ),
        )
        marts = self._mart_candidates(datasource_id, table_name, primary_date_column, table_type, sample_limit, profiled_at)
        return InferredTableProfile(table_profile=table_profile, column_profiles=column_profiles, join_paths=[], marts=marts)

    def infer_join_paths(
        self,
        datasource_id: str,
        table_profiles: list[InferredTableProfile],
        catalog_by_table: dict[str, list[DatasourceCatalogColumn]],
        sample_rows_by_table: dict[str, list[dict[str, Any]]],
        sample_limit: int,
    ) -> list[JoinPath]:
        profiled_at = utc_now_iso()
        candidates: list[JoinPath] = []
        tables = sorted(catalog_by_table)
        for left_table in tables:
            for right_table in tables:
                if left_table >= right_table:
                    continue
                for left in catalog_by_table[left_table]:
                    for right in catalog_by_table[right_table]:
                        confidence = self._join_confidence(left_table, left, right_table, right, sample_rows_by_table)
                        if confidence < 0.65:
                            continue
                        candidates.append(
                            JoinPath(
                                datasource_id=datasource_id,
                                left_table=left_table,
                                right_table=right_table,
                                join_condition=f"{left_table}.{left.column_name} = {right_table}.{right.column_name}",
                                relationship_type="candidate",
                                confidence=confidence,
                                metadata=self._metadata(
                                    sample_limit,
                                    profiled_at,
                                    {"join_condition": "inferred", "confidence": "inferred"},
                                    ["matched id column pattern"],
                                ),
                            )
                        )
        return sorted(candidates, key=lambda item: (-item.confidence, item.left_table, item.right_table))

    def _column_profile(
        self,
        datasource_id: str,
        schema_name: str | None,
        table_name: str,
        column: DatasourceCatalogColumn,
        sample_rows: list[dict[str, Any]],
        sample_limit: int,
        profiled_at: str,
    ) -> ColumnProfile:
        sample_values = self._sample_values(column.column_name, sample_rows)
        semantic_type = self._semantic_type(column, sample_values)
        return ColumnProfile(
            datasource_id=datasource_id,
            schema_name=schema_name,
            table_name=table_name,
            column_name=column.column_name,
            semantic_type=semantic_type,
            sample_values=sample_values,
            metadata=self._metadata(
                sample_limit,
                profiled_at,
                {"semantic_type": "inferred", "sample_values": "sample"},
                [f"semantic_type inferred as {semantic_type}"] if semantic_type else [],
            ),
        )

    def _semantic_type(self, column: DatasourceCatalogColumn, sample_values: list[str]) -> str | None:
        name = column.column_name.lower()
        data_type = column.data_type.lower()
        singular_table = column.table_name.lower().rstrip("s")
        if name == "id" or (name.endswith("_id") and name.startswith(singular_table)):
            return "identifier"
        if name.endswith("_id"):
            return "foreign_key"
        if "timestamp" in data_type or "datetime" in data_type:
            return "datetime"
        if "date" in data_type:
            return "date"
        if "timestamp" in name or "datetime" in name:
            return "datetime_string"
        if "date" in name:
            return "date_string"
        if any(token in data_type for token in ("int", "decimal", "numeric", "float", "double")):
            return "measure"
        if any(token in name for token in ("status", "type", "category", "code")):
            return "categorical"
        if any(token in data_type for token in ("bool", "tinyint(1)")):
            return "boolean"
        if any(token in data_type for token in ("text", "char", "varchar")):
            return "text"
        return None

    def _sample_values(self, column_name: str, sample_rows: list[dict[str, Any]]) -> list[str]:
        values: list[str] = []
        for row in sample_rows:
            value = row.get(column_name)
            if value is None:
                continue
            text = self._stringify(value)
            if text not in values:
                values.append(text)
            if len(values) >= 5:
                break
        return values

    def _stringify(self, value: Any) -> str:
        if isinstance(value, Decimal):
            return str(value)
        return str(value)

    def _primary_date_column(self, profiles: list[ColumnProfile]) -> str | None:
        preferred = ("created", "updated", "purchase", "order", "event")
        date_profiles = [
            profile
            for profile in profiles
            if profile.semantic_type in {"datetime", "date", "datetime_string", "date_string"}
        ]
        for token in preferred:
            for profile in date_profiles:
                if token in profile.column_name.lower():
                    return profile.column_name
        return date_profiles[0].column_name if date_profiles else None

    def _table_type(self, table_name: str) -> str:
        name = table_name.lower()
        if name.startswith("mart_") or name.endswith("_mart") or "_mart_" in name:
            return "mart"
        if name.startswith("dim_"):
            return "dimension"
        if name.startswith("fact_"):
            return "fact"
        return "raw"

    def _mart_candidates(
        self,
        datasource_id: str,
        table_name: str,
        date_column: str | None,
        table_type: str,
        sample_limit: int,
        profiled_at: str,
    ) -> list[MartDefinition]:
        name = table_name.lower()
        if table_type not in {"mart", "fact", "dimension"}:
            return []
        priority = 30 if name.startswith("mart_") else 20 if name.startswith("fact_") else 10
        return [
            MartDefinition(
                datasource_id=datasource_id,
                table_name=table_name,
                date_column=date_column,
                priority=priority,
                metadata=self._metadata(
                    sample_limit,
                    profiled_at,
                    {"table_name": "inferred", "date_column": "inferred", "priority": "inferred"},
                    [f"promoted {table_type} table"],
                ),
            )
        ]

    def _join_confidence(
        self,
        left_table: str,
        left: DatasourceCatalogColumn,
        right_table: str,
        right: DatasourceCatalogColumn,
        sample_rows_by_table: dict[str, list[dict[str, Any]]],
    ) -> float:
        left_name = left.column_name.lower()
        right_name = right.column_name.lower()
        confidence = 0.0
        if left_name == right_name and left_name.endswith("_id"):
            confidence = 0.7
        if left_name == "id" and right_name == f"{left_table.rstrip('s')}_id":
            confidence = 0.75
        if right_name == "id" and left_name == f"{right_table.rstrip('s')}_id":
            confidence = 0.75
        if confidence and left.data_type.lower() == right.data_type.lower():
            confidence += 0.05
        return min(confidence, 0.9)

    def _metadata(self, sample_limit: int, profiled_at: str, field_sources: dict[str, str], reasons: list[str]) -> dict[str, object]:
        return {
            "field_sources": field_sources,
            "profile": {
                "strategy": "limit",
                "sample_limit": sample_limit,
                "sampled_columns_limit": 20,
                "profiled_at": profiled_at,
                "source": "rule_based_sample",
            },
            "inference": {"version": self.version, "reasons": reasons},
        }
