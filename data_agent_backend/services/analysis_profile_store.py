from __future__ import annotations

from data_agent_backend.models.analysis_context import ColumnProfile, TableProfile
from data_agent_backend.models.common import utc_now_iso
from data_agent_backend.storage.sqlite import SQLiteStore, dumps_json, loads_json


class AnalysisProfileStore:
    def __init__(self, sqlite: SQLiteStore) -> None:
        self.sqlite = sqlite

    def upsert_table_profile(self, profile: TableProfile) -> TableProfile:
        existing = self.get_table_profile(profile.datasource_id, profile.table_name, profile.schema_name)
        if existing is not None:
            profile = self._merge_table_profile(existing, profile)
        now = utc_now_iso()
        self.sqlite.execute(
            """
            INSERT INTO datasource_table_profiles(
                datasource_id, schema_name, table_name, row_count, table_type,
                description, primary_date_column, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(datasource_id, table_name) DO UPDATE SET
                schema_name = excluded.schema_name,
                row_count = excluded.row_count,
                table_type = excluded.table_type,
                description = excluded.description,
                primary_date_column = excluded.primary_date_column,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                profile.datasource_id,
                profile.schema_name,
                profile.table_name,
                profile.row_count,
                profile.table_type,
                profile.description,
                profile.primary_date_column,
                dumps_json(profile.metadata),
                now,
            ),
        )
        return self.get_table_profile(profile.datasource_id, profile.table_name, profile.schema_name) or profile

    def get_table_profile(self, datasource_id: str, table_name: str, schema_name: str | None = None) -> TableProfile | None:
        row = self.sqlite.query_one(
            """
            SELECT * FROM datasource_table_profiles
            WHERE datasource_id = ? AND table_name = ?
            """,
            (datasource_id, table_name),
        )
        if row is None:
            return None
        if schema_name is not None and row["schema_name"] not in (None, schema_name):
            return None
        return self._table_from_row(row)

    def list_table_profiles(self, datasource_id: str) -> list[TableProfile]:
        rows = self.sqlite.query_all(
            "SELECT * FROM datasource_table_profiles WHERE datasource_id = ? ORDER BY table_name",
            (datasource_id,),
        )
        return [self._table_from_row(row) for row in rows]

    def upsert_column_profile(self, profile: ColumnProfile) -> ColumnProfile:
        existing = self.get_column_profile(profile.datasource_id, profile.table_name, profile.column_name, profile.schema_name)
        if existing is not None:
            profile = self._merge_column_profile(existing, profile)
        now = utc_now_iso()
        self.sqlite.execute(
            """
            INSERT INTO datasource_column_profiles(
                datasource_id, schema_name, table_name, column_name, semantic_type,
                description, null_ratio, distinct_count, sample_values_json,
                metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(datasource_id, table_name, column_name) DO UPDATE SET
                schema_name = excluded.schema_name,
                semantic_type = excluded.semantic_type,
                description = excluded.description,
                null_ratio = excluded.null_ratio,
                distinct_count = excluded.distinct_count,
                sample_values_json = excluded.sample_values_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                profile.datasource_id,
                profile.schema_name,
                profile.table_name,
                profile.column_name,
                profile.semantic_type,
                profile.description,
                profile.null_ratio,
                profile.distinct_count,
                dumps_json(profile.sample_values),
                dumps_json(profile.metadata),
                now,
            ),
        )
        return self.get_column_profile(profile.datasource_id, profile.table_name, profile.column_name, profile.schema_name) or profile

    def get_column_profile(self, datasource_id: str, table_name: str, column_name: str, schema_name: str | None = None) -> ColumnProfile | None:
        row = self.sqlite.query_one(
            """
            SELECT * FROM datasource_column_profiles
            WHERE datasource_id = ? AND table_name = ? AND column_name = ?
            """,
            (datasource_id, table_name, column_name),
        )
        if row is None:
            return None
        if schema_name is not None and row["schema_name"] not in (None, schema_name):
            return None
        return self._column_from_row(row)

    def list_column_profiles(self, datasource_id: str, table_name: str | None = None) -> list[ColumnProfile]:
        if table_name is None:
            rows = self.sqlite.query_all(
                "SELECT * FROM datasource_column_profiles WHERE datasource_id = ? ORDER BY table_name, column_name",
                (datasource_id,),
            )
        else:
            rows = self.sqlite.query_all(
                """
                SELECT * FROM datasource_column_profiles
                WHERE datasource_id = ? AND table_name = ?
                ORDER BY column_name
                """,
                (datasource_id, table_name),
            )
        return [self._column_from_row(row) for row in rows]

    def _table_from_row(self, row) -> TableProfile:
        return TableProfile(
            datasource_id=row["datasource_id"],
            schema_name=row["schema_name"],
            table_name=row["table_name"],
            row_count=row["row_count"],
            table_type=row["table_type"],
            description=row["description"],
            primary_date_column=row["primary_date_column"],
            metadata=loads_json(row["metadata_json"]),
        )

    def _column_from_row(self, row) -> ColumnProfile:
        return ColumnProfile(
            datasource_id=row["datasource_id"],
            schema_name=row["schema_name"],
            table_name=row["table_name"],
            column_name=row["column_name"],
            semantic_type=row["semantic_type"],
            description=row["description"],
            null_ratio=row["null_ratio"],
            distinct_count=row["distinct_count"],
            sample_values=loads_json(row["sample_values_json"], []),
            metadata=loads_json(row["metadata_json"]),
        )

    def _merge_table_profile(self, existing: TableProfile, incoming: TableProfile) -> TableProfile:
        return incoming.model_copy(
            update={
                "row_count": existing.row_count if self._is_manual(existing.metadata, "row_count") else incoming.row_count,
                "table_type": existing.table_type if self._is_manual(existing.metadata, "table_type") else incoming.table_type,
                "description": existing.description if self._is_manual(existing.metadata, "description") else incoming.description,
                "primary_date_column": existing.primary_date_column
                if self._is_manual(existing.metadata, "primary_date_column")
                else incoming.primary_date_column,
                "metadata": self._merge_metadata(existing.metadata, incoming.metadata),
            }
        )

    def _merge_column_profile(self, existing: ColumnProfile, incoming: ColumnProfile) -> ColumnProfile:
        return incoming.model_copy(
            update={
                "semantic_type": existing.semantic_type if self._is_manual(existing.metadata, "semantic_type") else incoming.semantic_type,
                "description": existing.description if self._is_manual(existing.metadata, "description") else incoming.description,
                "null_ratio": existing.null_ratio if self._is_manual(existing.metadata, "null_ratio") else incoming.null_ratio,
                "distinct_count": existing.distinct_count if self._is_manual(existing.metadata, "distinct_count") else incoming.distinct_count,
                "sample_values": existing.sample_values if self._is_manual(existing.metadata, "sample_values") else incoming.sample_values,
                "metadata": self._merge_metadata(existing.metadata, incoming.metadata),
            }
        )

    def _is_manual(self, profile_metadata: dict, field_name: str) -> bool:
        return profile_metadata.get("field_sources", {}).get(field_name) == "manual"

    def _merge_metadata(self, existing: dict, incoming: dict) -> dict:
        merged = dict(existing)
        for key, value in incoming.items():
            if key == "field_sources":
                sources = dict(existing.get("field_sources", {}))
                for field_name, source in value.items():
                    if sources.get(field_name) != "manual":
                        sources[field_name] = source
                merged["field_sources"] = sources
            elif isinstance(value, dict) and isinstance(existing.get(key), dict):
                nested = dict(existing[key])
                nested.update(value)
                merged[key] = nested
            else:
                merged[key] = value
        return merged
