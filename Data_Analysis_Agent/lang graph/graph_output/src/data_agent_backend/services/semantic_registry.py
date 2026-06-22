from __future__ import annotations

from data_agent_backend.models.analysis_context import (
    BusinessTerm,
    JoinPath,
    MartDefinition,
    MetricDefinition,
    SemanticSearchResult,
    SemanticSeedLoadResult,
)
from data_agent_backend.models.common import JsonDict
from data_agent_backend.models.common import utc_now_iso
from data_agent_backend.storage.sqlite import SQLiteStore, dumps_json, loads_json


class SemanticRegistry:
    def __init__(self, sqlite: SQLiteStore) -> None:
        self.sqlite = sqlite

    def upsert_metric(self, metric: MetricDefinition) -> MetricDefinition:
        now = utc_now_iso()
        self.sqlite.execute(
            """
            INSERT INTO semantic_metrics(
                datasource_id, name, description, expression, recommended_table,
                filters_json, dimensions_json, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(datasource_id, name) DO UPDATE SET
                description = excluded.description,
                expression = excluded.expression,
                recommended_table = excluded.recommended_table,
                filters_json = excluded.filters_json,
                dimensions_json = excluded.dimensions_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                metric.datasource_id,
                metric.name,
                metric.description,
                metric.expression,
                metric.recommended_table,
                dumps_json(metric.filters),
                dumps_json(metric.dimensions),
                dumps_json(metric.metadata),
                now,
            ),
        )
        return metric

    def upsert_business_term(self, term: BusinessTerm) -> BusinessTerm:
        now = utc_now_iso()
        self.sqlite.execute(
            """
            INSERT INTO semantic_terms(
                datasource_id, term, description, related_tables_json,
                related_columns_json, related_metrics_json, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(datasource_id, term) DO UPDATE SET
                description = excluded.description,
                related_tables_json = excluded.related_tables_json,
                related_columns_json = excluded.related_columns_json,
                related_metrics_json = excluded.related_metrics_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                term.datasource_id,
                term.term,
                term.description,
                dumps_json(term.related_tables),
                dumps_json(term.related_columns),
                dumps_json(term.related_metrics),
                dumps_json(term.metadata),
                now,
            ),
        )
        return term

    def upsert_mart(self, mart: MartDefinition) -> MartDefinition:
        existing = self._get_mart(mart.datasource_id, mart.table_name)
        if existing is not None:
            mart = mart.model_copy(
                update={
                    "description": existing.description if self._is_manual(existing.metadata, "description") else mart.description,
                    "grain": existing.grain if self._is_manual(existing.metadata, "grain") else mart.grain,
                    "date_column": existing.date_column if self._is_manual(existing.metadata, "date_column") else mart.date_column,
                    "priority": existing.priority if self._is_manual(existing.metadata, "priority") else mart.priority,
                    "related_metrics": existing.related_metrics
                    if self._is_manual(existing.metadata, "related_metrics")
                    else mart.related_metrics,
                    "metadata": self._merge_metadata(existing.metadata, mart.metadata),
                }
            )
        now = utc_now_iso()
        self.sqlite.execute(
            """
            INSERT INTO semantic_marts(
                datasource_id, table_name, description, grain, date_column,
                priority, related_metrics_json, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(datasource_id, table_name) DO UPDATE SET
                description = excluded.description,
                grain = excluded.grain,
                date_column = excluded.date_column,
                priority = excluded.priority,
                related_metrics_json = excluded.related_metrics_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                mart.datasource_id,
                mart.table_name,
                mart.description,
                mart.grain,
                mart.date_column,
                mart.priority,
                dumps_json(mart.related_metrics),
                dumps_json(mart.metadata),
                now,
            ),
        )
        return mart

    def upsert_join_path(self, join_path: JoinPath) -> JoinPath:
        existing = self._get_join_path(join_path.datasource_id, join_path.left_table, join_path.right_table, join_path.join_condition)
        if existing is not None:
            join_path = join_path.model_copy(
                update={
                    "relationship_type": existing.relationship_type
                    if self._is_manual(existing.metadata, "relationship_type")
                    else join_path.relationship_type,
                    "confidence": existing.confidence if self._is_manual(existing.metadata, "confidence") else join_path.confidence,
                    "metadata": self._merge_metadata(existing.metadata, join_path.metadata),
                }
            )
        now = utc_now_iso()
        self.sqlite.execute(
            """
            INSERT INTO semantic_join_paths(
                datasource_id, left_table, right_table, join_condition,
                relationship_type, confidence, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(datasource_id, left_table, right_table, join_condition) DO UPDATE SET
                relationship_type = excluded.relationship_type,
                confidence = excluded.confidence,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                join_path.datasource_id,
                join_path.left_table,
                join_path.right_table,
                join_path.join_condition,
                join_path.relationship_type,
                join_path.confidence,
                dumps_json(join_path.metadata),
                now,
            ),
        )
        return join_path

    def load_seed(self, datasource_id: str, seed: JsonDict) -> SemanticSeedLoadResult:
        counts = SemanticSeedLoadResult()
        for item in seed.get("metrics", []):
            self.upsert_metric(MetricDefinition(datasource_id=datasource_id, **item))
            counts.metrics += 1
        for item in seed.get("business_terms", seed.get("terms", [])):
            self.upsert_business_term(BusinessTerm(datasource_id=datasource_id, **item))
            counts.business_terms += 1
        for item in seed.get("marts", []):
            self.upsert_mart(MartDefinition(datasource_id=datasource_id, **item))
            counts.marts += 1
        for item in seed.get("join_paths", []):
            self.upsert_join_path(JoinPath(datasource_id=datasource_id, **item))
            counts.join_paths += 1
        return counts

    def search(self, datasource_id: str, query: str, limit: int = 10) -> SemanticSearchResult:
        metrics = [item for item in self.list_metrics(datasource_id) if self._matches(query, item.model_dump(mode="json"))][:limit]
        business_terms = [item for item in self.list_business_terms(datasource_id) if self._matches(query, item.model_dump(mode="json"))][:limit]
        marts = [item for item in self.list_marts(datasource_id) if self._matches(query, item.model_dump(mode="json"))][:limit]
        return SemanticSearchResult(datasource_id=datasource_id, query=query, metrics=metrics, business_terms=business_terms, marts=marts)

    def list_metrics(self, datasource_id: str) -> list[MetricDefinition]:
        rows = self.sqlite.query_all("SELECT * FROM semantic_metrics WHERE datasource_id = ? ORDER BY name", (datasource_id,))
        return [self._metric_from_row(row) for row in rows]

    def list_business_terms(self, datasource_id: str) -> list[BusinessTerm]:
        rows = self.sqlite.query_all("SELECT * FROM semantic_terms WHERE datasource_id = ? ORDER BY term", (datasource_id,))
        return [self._term_from_row(row) for row in rows]

    def list_marts(self, datasource_id: str) -> list[MartDefinition]:
        rows = self.sqlite.query_all("SELECT * FROM semantic_marts WHERE datasource_id = ? ORDER BY priority DESC, table_name", (datasource_id,))
        return [self._mart_from_row(row) for row in rows]

    def get_join_paths(self, datasource_id: str, table_names: list[str]) -> list[JoinPath]:
        rows = self.sqlite.query_all(
            "SELECT * FROM semantic_join_paths WHERE datasource_id = ? ORDER BY confidence DESC, left_table, right_table",
            (datasource_id,),
        )
        requested = set(table_names)
        joins = [self._join_from_row(row) for row in rows]
        if not requested:
            return joins
        return [join for join in joins if join.left_table in requested or join.right_table in requested]

    def _matches(self, query: str, payload: object) -> bool:
        haystack = str(payload).lower().replace("_", " ")
        needles = [token for token in query.lower().replace("_", " ").split() if token]
        return any(token in haystack for token in needles)

    def _metric_from_row(self, row) -> MetricDefinition:
        return MetricDefinition(
            datasource_id=row["datasource_id"],
            name=row["name"],
            description=row["description"],
            expression=row["expression"],
            recommended_table=row["recommended_table"],
            filters=loads_json(row["filters_json"], []),
            dimensions=loads_json(row["dimensions_json"], []),
            metadata=loads_json(row["metadata_json"]),
        )

    def _term_from_row(self, row) -> BusinessTerm:
        return BusinessTerm(
            datasource_id=row["datasource_id"],
            term=row["term"],
            description=row["description"],
            related_tables=loads_json(row["related_tables_json"], []),
            related_columns=loads_json(row["related_columns_json"], []),
            related_metrics=loads_json(row["related_metrics_json"], []),
            metadata=loads_json(row["metadata_json"]),
        )

    def _mart_from_row(self, row) -> MartDefinition:
        return MartDefinition(
            datasource_id=row["datasource_id"],
            table_name=row["table_name"],
            description=row["description"],
            grain=row["grain"],
            date_column=row["date_column"],
            priority=row["priority"],
            related_metrics=loads_json(row["related_metrics_json"], []),
            metadata=loads_json(row["metadata_json"]),
        )

    def _join_from_row(self, row) -> JoinPath:
        return JoinPath(
            datasource_id=row["datasource_id"],
            left_table=row["left_table"],
            right_table=row["right_table"],
            join_condition=row["join_condition"],
            relationship_type=row["relationship_type"],
            confidence=row["confidence"],
            metadata=loads_json(row["metadata_json"]),
        )

    def _get_mart(self, datasource_id: str, table_name: str) -> MartDefinition | None:
        row = self.sqlite.query_one(
            "SELECT * FROM semantic_marts WHERE datasource_id = ? AND table_name = ?",
            (datasource_id, table_name),
        )
        return self._mart_from_row(row) if row is not None else None

    def _get_join_path(self, datasource_id: str, left_table: str, right_table: str, join_condition: str) -> JoinPath | None:
        row = self.sqlite.query_one(
            """
            SELECT * FROM semantic_join_paths
            WHERE datasource_id = ? AND left_table = ? AND right_table = ? AND join_condition = ?
            """,
            (datasource_id, left_table, right_table, join_condition),
        )
        return self._join_from_row(row) if row is not None else None

    def _is_manual(self, metadata: dict, field_name: str) -> bool:
        return metadata.get("field_sources", {}).get(field_name) == "manual"

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
