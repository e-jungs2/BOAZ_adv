from __future__ import annotations

import re
from collections.abc import Callable

from data_agent_backend.models.analysis_context import (
    AnalysisWarning,
    AnalysisContext,
    CatalogSearchColumn,
    CatalogSearchMatch,
    CatalogSearchResult,
    ColumnProfile,
    JoinHint,
    MartDefinition,
    MetricHint,
    MetricDefinition,
    RecommendedColumn,
    RecommendedTable,
    SemanticSearchResult,
    TableProfile,
    TimeFilterHint,
)
from data_agent_backend.models.datasources import DatasourceCatalogColumn, DatasourceDialectCapabilities
from data_agent_backend.services.analysis_profile_store import AnalysisProfileStore
from data_agent_backend.services.datasource_registry import DatasourceRegistry
from data_agent_backend.services.semantic_registry import SemanticRegistry


QUERY_SYNONYMS = {
    "배송": ["delivery", "delivered", "carrier", "estimated", "shipping", "freight"],
    "리뷰": ["review", "score", "comment"],
    "평점": ["review", "score"],
    "주문": ["order", "orders", "item"],
    "상품": ["product", "category"],
    "판매자": ["seller"],
    "가격": ["price", "payment", "value"],
    "운임": ["freight"],
    "지역": ["city", "state", "zip"],
    "카테고리": ["category"],
    "고객": ["customer"],
    "빠르": ["delivery", "delivered", "carrier", "timestamp"],
    "낮": ["review", "score"],
}

COLUMN_REFERENCE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")


class AnalysisContextService:
    def __init__(
        self,
        datasource_registry: DatasourceRegistry,
        profile_store: AnalysisProfileStore,
        semantic_registry: SemanticRegistry,
        dialect_capabilities_provider: Callable[[str], DatasourceDialectCapabilities] | None = None,
    ) -> None:
        self.datasource_registry = datasource_registry
        self.profile_store = profile_store
        self.semantic_registry = semantic_registry
        self.dialect_capabilities_provider = dialect_capabilities_provider

    def catalog_search(self, datasource_id: str, query: str, limit: int = 10) -> CatalogSearchResult:
        self.datasource_registry.get(datasource_id)
        columns = self.datasource_registry.get_catalog(datasource_id)
        matches = self._catalog_matches(datasource_id, columns, query, limit)
        return CatalogSearchResult(datasource_id=datasource_id, query=query, matches=matches)

    def get_table_profile(self, datasource_id: str, table_name: str, schema_name: str | None = None) -> TableProfile | None:
        self.datasource_registry.get(datasource_id)
        return self.profile_store.get_table_profile(datasource_id, table_name, schema_name)

    def get_column_profile(self, datasource_id: str, table_name: str, column_name: str, schema_name: str | None = None) -> ColumnProfile | None:
        self.datasource_registry.get(datasource_id)
        return self.profile_store.get_column_profile(datasource_id, table_name, column_name, schema_name)

    def semantic_search(self, datasource_id: str, query: str, limit: int = 10) -> SemanticSearchResult:
        self.datasource_registry.get(datasource_id)
        return self.semantic_registry.search(datasource_id, query, limit)

    def get_join_paths(self, datasource_id: str, table_names: list[str]) -> list:
        self.datasource_registry.get(datasource_id)
        return self.semantic_registry.get_join_paths(datasource_id, table_names)

    def build_analysis_context(self, datasource_id: str, question: str, limit: int = 10) -> AnalysisContext:
        self.datasource_registry.get(datasource_id)
        dialect_capabilities = self._dialect_capabilities(datasource_id)
        semantic = self.semantic_registry.search(datasource_id, question, limit)
        marts = semantic.marts or self.semantic_registry.list_marts(datasource_id)[:limit]
        catalog = self.catalog_search(datasource_id, question, limit)
        catalog_matches = list(catalog.matches)

        semantic_tables = self._semantic_table_hints(semantic)
        semantic_tables.extend(mart.table_name for mart in marts)
        semantic_column_hints = self._semantic_column_hints(semantic, marts)
        semantic_tables.extend(table for table, _column in semantic_column_hints if table)
        catalog_matches = self._merge_catalog_matches(datasource_id, catalog_matches, list(dict.fromkeys(semantic_tables)), limit)
        matched_tables = [match.table_name for match in catalog_matches]

        table_profiles = [profile for table in matched_tables if (profile := self.profile_store.get_table_profile(datasource_id, table)) is not None]
        column_profiles = [
            profile
            for table in matched_tables
            for profile in self.profile_store.list_column_profiles(datasource_id, table)
        ]
        join_paths = self.semantic_registry.get_join_paths(datasource_id, matched_tables)
        recommended_tables = self._recommended_tables(catalog_matches, table_profiles)
        recommended_columns = self._recommended_columns(catalog_matches, column_profiles, semantic_column_hints)
        time_filter_hints = self._time_filter_hints(recommended_columns, dialect_capabilities)
        metric_hints = self._metric_hints(semantic.metrics, recommended_columns)
        join_hints = self._join_hints(datasource_id, join_paths, recommended_tables)
        analysis_warnings = self._analysis_warnings(
            recommended_tables,
            table_profiles,
            column_profiles,
            join_hints,
            dialect_capabilities,
        )

        return AnalysisContext(
            datasource_id=datasource_id,
            question=question,
            catalog_matches=catalog_matches,
            table_profiles=table_profiles,
            column_profiles=column_profiles,
            metrics=semantic.metrics,
            business_terms=semantic.business_terms,
            marts=marts,
            join_paths=join_paths,
            dialect_capabilities=dialect_capabilities,
            query_guidance=self._query_guidance(dialect_capabilities),
            recommended_tables=recommended_tables,
            recommended_columns=recommended_columns,
            time_filter_hints=time_filter_hints,
            metric_hints=metric_hints,
            join_hints=join_hints,
            analysis_warnings=analysis_warnings,
            usage_notes=[
                "Use mart candidates before raw tables when they answer the question.",
                "Use table and column profiles to avoid expensive broad joins or function-wrapped filters.",
                "Use join paths as hints and still verify referenced columns exist in catalog matches.",
            ],
        )

    def _catalog_matches(self, datasource_id: str, columns: list[DatasourceCatalogColumn], query: str, limit: int) -> list[CatalogSearchMatch]:
        grouped: dict[tuple[str | None, str], list[DatasourceCatalogColumn]] = {}
        for column in columns:
            grouped.setdefault((column.schema_name, column.table_name), []).append(column)

        matches: list[CatalogSearchMatch] = []
        for (schema_name, table_name), table_columns in grouped.items():
            table_hit = self._matches(query, [schema_name, table_name])
            column_hits = [
                CatalogSearchColumn(
                    name=column.column_name,
                    data_type=column.data_type,
                    nullable=column.nullable,
                    reason="matched column name",
                )
                for column in table_columns
                if self._matches(query, [column.column_name, column.data_type, column.metadata])
            ]
            if not table_hit and not column_hits:
                continue
            confidence = 0.8 if table_hit else 0.65
            if column_hits:
                confidence += min(0.15, len(column_hits) * 0.05)
            matches.append(
                CatalogSearchMatch(
                    datasource_id=datasource_id,
                    schema_name=schema_name,
                    table_name=table_name,
                    columns=column_hits or [
                        CatalogSearchColumn(
                            name=column.column_name,
                            data_type=column.data_type,
                            nullable=column.nullable,
                            reason="included from matched table",
                        )
                        for column in table_columns[:5]
                    ],
                    reason="matched table name" if table_hit else "matched column name",
                    confidence=min(confidence, 0.95),
                )
            )
        return sorted(matches, key=lambda item: (-item.confidence, item.table_name))[:limit]

    def _recommended_tables(
        self,
        matches: list[CatalogSearchMatch],
        table_profiles: list[TableProfile],
    ) -> list[RecommendedTable]:
        profiled = {
            (profile.schema_name, profile.table_name)
            for profile in table_profiles
        }
        recommendations: list[RecommendedTable] = []
        for match in matches:
            has_profile = (match.schema_name, match.table_name) in profiled
            source = "profile" if has_profile else "catalog"
            warnings = [] if has_profile else ["No stored table profile is available for this table."]
            recommendations.append(
                RecommendedTable(
                    schema_name=match.schema_name,
                    table_name=match.table_name,
                    reason=match.reason,
                    confidence=match.confidence,
                    source=source,
                    warnings=warnings,
                )
            )
        return recommendations

    def _recommended_columns(
        self,
        matches: list[CatalogSearchMatch],
        column_profiles: list[ColumnProfile],
        semantic_column_hints: set[tuple[str | None, str]],
    ) -> list[RecommendedColumn]:
        profile_by_key = {
            (profile.schema_name, profile.table_name, profile.column_name): profile
            for profile in column_profiles
        }
        recommendations: list[RecommendedColumn] = []
        seen: set[tuple[str | None, str, str]] = set()
        for match in matches:
            catalog_columns = [
                column
                for column in self.datasource_registry.get_catalog(match.datasource_id, match.table_name)
                if column.schema_name == match.schema_name
            ]
            matched_names = {column.name for column in match.columns}
            for column in catalog_columns:
                semantic_hit = self._semantic_column_hit(column.table_name, column.column_name, semantic_column_hints)
                if matched_names and column.column_name not in matched_names and not self._important_column(column.column_name) and not semantic_hit:
                    continue
                key = (column.schema_name, column.table_name, column.column_name)
                if key in seen:
                    continue
                profile = profile_by_key.get(key)
                role = self._column_role(column.column_name, column.data_type, profile.semantic_type if profile else None)
                recommendations.append(
                    RecommendedColumn(
                        schema_name=column.schema_name,
                        table_name=column.table_name,
                        column_name=column.column_name,
                        data_type=column.data_type,
                        semantic_type=profile.semantic_type if profile else None,
                        role=role,
                        reason="matched semantic registry column hint" if semantic_hit else f"{role} candidate from catalog match",
                        confidence=0.85 if semantic_hit else 0.8 if profile else 0.65,
                    )
                )
                seen.add(key)
        return sorted(recommendations, key=lambda item: (-item.confidence, item.table_name, item.column_name))

    def _semantic_column_hints(
        self,
        semantic: SemanticSearchResult,
        marts: list[MartDefinition],
    ) -> set[tuple[str | None, str]]:
        hints: set[tuple[str | None, str]] = set()
        for metric in semantic.metrics:
            hints.update(self._column_hint_names(metric.dimensions))
            hints.update(self._column_hint_names(metric.filters))
        for term in semantic.business_terms:
            hints.update(self._column_hint_names(term.related_columns))
        for mart in marts:
            if mart.date_column:
                hints.update(self._column_hint_names([mart.date_column]))
        return hints

    def _column_hint_names(self, values: list[str]) -> set[tuple[str | None, str]]:
        hints: set[tuple[str | None, str]] = set()
        for value in values:
            for reference in COLUMN_REFERENCE_RE.findall(value):
                parts = reference.lower().split(".")
                if len(parts) == 2:
                    hints.add((parts[0], parts[1]))
                else:
                    hints.add((None, parts[0]))
        return hints

    def _semantic_column_hit(
        self,
        table_name: str,
        column_name: str,
        semantic_column_hints: set[tuple[str | None, str]],
    ) -> bool:
        table = table_name.lower()
        column = column_name.lower()
        return (None, column) in semantic_column_hints or (table, column) in semantic_column_hints

    def _important_column(self, column_name: str) -> bool:
        name = column_name.lower()
        tokens = (
            "review",
            "score",
            "price",
            "freight",
            "delivered",
            "delivery",
            "estimated",
            "carrier",
            "date",
            "timestamp",
            "order_id",
            "product_id",
            "seller_id",
            "customer_id",
            "category",
            "city",
            "state",
        )
        return any(token in name for token in tokens)

    def _column_role(self, column_name: str, data_type: str, semantic_type: str | None) -> str:
        name = column_name.lower()
        dtype = data_type.lower()
        if semantic_type in {"datetime", "date", "datetime_string", "date_string"}:
            return "time"
        if any(token in name for token in ("date", "timestamp", "delivered", "estimated", "carrier")):
            return "time"
        if name in {"review_score", "price", "freight_value"}:
            return "metric"
        if any(token in dtype for token in ("int", "decimal", "numeric", "float", "double")) and not name.endswith("_id"):
            return "metric"
        if name.endswith("_id"):
            return "join_key"
        if any(token in name for token in ("category", "status", "type", "city", "state")):
            return "dimension"
        return "identifier" if name == "id" else "dimension"

    def _time_filter_hints(
        self,
        columns: list[RecommendedColumn],
        capabilities: DatasourceDialectCapabilities | None,
    ) -> list[TimeFilterHint]:
        by_table: dict[tuple[str | None, str], set[str]] = {}
        for column in columns:
            if column.role == "time":
                by_table.setdefault((column.schema_name, column.table_name), set()).add(column.column_name)

        hints: list[TimeFilterHint] = []
        dialect = capabilities.dialect if capabilities else None
        for schema_name, table_name in sorted(by_table, key=lambda key: (key[0] or "", key[1])):
            if table_name != "orders":
                continue
            order_columns = by_table[(schema_name, table_name)]
            if {"order_delivered_carrier_date", "order_delivered_customer_date"} <= order_columns:
                expression = (
                    "TIMESTAMPDIFF(HOUR, order_delivered_carrier_date, order_delivered_customer_date) / 24.0"
                    if dialect == "mysql"
                    else "order_delivered_customer_date - order_delivered_carrier_date"
                )
                hints.append(
                    TimeFilterHint(
                        name="delivery_days",
                        table_name="orders",
                        column_names=["order_delivered_carrier_date", "order_delivered_customer_date"],
                        expression_hint=expression,
                        dialect=dialect,
                        reason="배송 소요 시간을 계산하는 후보입니다.",
                    )
                )
            if {"order_estimated_delivery_date", "order_delivered_customer_date"} <= order_columns:
                expression = (
                    "TIMESTAMPDIFF(HOUR, order_estimated_delivery_date, order_delivered_customer_date) / 24.0"
                    if dialect == "mysql"
                    else "order_delivered_customer_date - order_estimated_delivery_date"
                )
                hints.append(
                    TimeFilterHint(
                        name="delivery_delay_days",
                        table_name="orders",
                        column_names=["order_estimated_delivery_date", "order_delivered_customer_date"],
                        expression_hint=expression,
                        dialect=dialect,
                        reason="예상 배송일 대비 지연 여부를 계산하는 후보입니다.",
                    )
                )
        return hints

    def _metric_hints(
        self,
        semantic_metrics: list[MetricDefinition],
        columns: list[RecommendedColumn],
    ) -> list[MetricHint]:
        hints: list[MetricHint] = []
        existing: set[tuple[str, str | None, str]] = set()
        for metric in semantic_metrics:
            key = ("semantic", metric.recommended_table, metric.expression)
            if key in existing:
                continue
            hints.append(
                MetricHint(
                    name=metric.name,
                    expression_hint=metric.expression,
                    table_name=metric.recommended_table,
                    column_names=[],
                    reason=metric.description or "semantic registry metric",
                    source="semantic",
                )
            )
            existing.add(key)
        for column in columns:
            if column.role != "metric":
                continue
            metric_name = column.column_name
            key = ("catalog", column.table_name, column.column_name)
            if key in existing:
                continue
            hints.append(
                MetricHint(
                    name=metric_name,
                    expression_hint=column.column_name,
                    table_name=column.table_name,
                    column_names=[column.column_name],
                    reason=f"{column.column_name} can be used as an analysis metric.",
                    source="catalog",
                )
            )
            existing.add(key)
        if ("inferred", None, "COUNT(DISTINCT order_id)") not in existing and any(column.column_name == "order_id" for column in columns):
            hints.append(
                MetricHint(
                    name="order_count",
                    expression_hint="COUNT(DISTINCT order_id)",
                    table_name=None,
                    column_names=["order_id"],
                    reason="주문 수를 비교하기 위한 기본 집계 후보입니다.",
                    source="inferred",
                )
            )
        return hints

    def _join_hints(
        self,
        datasource_id: str,
        stored_join_paths: list,
        recommended_tables: list[RecommendedTable],
    ) -> list[JoinHint]:
        hints = [
            JoinHint(
                left_table=join.left_table,
                right_table=join.right_table,
                join_condition=join.join_condition,
                relationship_type=join.relationship_type,
                confidence=join.confidence,
                source="semantic_registry",
                warnings=[],
            )
            for join in stored_join_paths
        ]
        seen = {(hint.left_table, hint.right_table, hint.join_condition) for hint in hints}
        table_keys = [(table.schema_name, table.table_name) for table in recommended_tables]
        catalog_by_table = {
            table_key: [
                column
                for column in self.datasource_registry.get_catalog(datasource_id, table_key[1])
                if column.schema_name == table_key[0]
            ]
            for table_key in table_keys
        }
        for left_index, left_key in enumerate(table_keys):
            left_schema, left_table = left_key
            for right_key in table_keys[left_index + 1 :]:
                right_schema, right_table = right_key
                if left_schema is not None and right_schema is not None and left_schema != right_schema:
                    continue
                for left in catalog_by_table.get(left_key, []):
                    for right in catalog_by_table.get(right_key, []):
                        if left.column_name != right.column_name or not left.column_name.endswith("_id"):
                            continue
                        condition = f"{left_table}.{left.column_name} = {right_table}.{right.column_name}"
                        key = (left_table, right_table, condition)
                        if key in seen:
                            continue
                        hints.append(
                            JoinHint(
                                left_table=left_table,
                                right_table=right_table,
                                join_condition=condition,
                                relationship_type="candidate",
                                confidence=0.65,
                                source="catalog_inferred",
                                warnings=["Catalog name based join candidate; cardinality is not verified."],
                            )
                        )
                        seen.add(key)
        return sorted(hints, key=lambda item: (-item.confidence, item.left_table, item.right_table))

    def _analysis_warnings(
        self,
        recommended_tables: list[RecommendedTable],
        table_profiles: list[TableProfile],
        column_profiles: list[ColumnProfile],
        join_hints: list[JoinHint],
        dialect_capabilities: DatasourceDialectCapabilities | None,
    ) -> list[AnalysisWarning]:
        warnings: list[AnalysisWarning] = []
        table_profile_keys = {
            (profile.schema_name, profile.table_name)
            for profile in table_profiles
        }
        column_profile_tables = {
            (profile.schema_name, profile.table_name)
            for profile in column_profiles
        }
        missing_profile_tables = [
            table.table_name
            for table in recommended_tables
            if (table.schema_name, table.table_name) not in table_profile_keys
            or (table.schema_name, table.table_name) not in column_profile_tables
        ]
        if missing_profile_tables:
            warnings.append(
                AnalysisWarning(
                    code="profile_missing",
                    message="No stored table or column profiles are available for at least one recommended table.",
                    severity="warning",
                    details={"table_names": missing_profile_tables},
                )
            )
        if any(hint.source == "catalog_inferred" for hint in join_hints):
            warnings.append(
                AnalysisWarning(
                    code="join_unverified",
                    message="One or more join hints are inferred from catalog names and have not been validated against data cardinality.",
                    severity="warning",
                    details={"join_count": len([hint for hint in join_hints if hint.source == "catalog_inferred"])},
                )
            )
        table_names = {table.table_name for table in recommended_tables}
        if "orders" in table_names and "order_items" in table_names:
            warnings.append(
                AnalysisWarning(
                    code="grain_risk",
                    message="Joining order-level and item-level tables can multiply rows; aggregate at the intended grain.",
                    severity="warning",
                    details={"tables": ["orders", "order_items"]},
                )
            )
        if dialect_capabilities is None:
            warnings.append(
                AnalysisWarning(
                    code="dialect_guidance_missing",
                    message="Datasource SQL dialect guidance is not available.",
                    severity="warning",
                    details={},
                )
            )
        if missing_profile_tables:
            warnings.append(
                AnalysisWarning(
                    code="context_partial",
                    message="Context recommendations are based on catalog and semantic hints only.",
                    severity="info",
                    details={},
                )
            )
        return warnings

    def _merge_catalog_matches(
        self,
        datasource_id: str,
        matches: list[CatalogSearchMatch],
        table_names: list[str],
        limit: int,
    ) -> list[CatalogSearchMatch]:
        seen = {match.table_name for match in matches}
        for table_name in table_names:
            if table_name in seen:
                continue
            catalog_columns = self.datasource_registry.get_catalog(datasource_id, table_name)
            if not catalog_columns:
                matches.append(
                    CatalogSearchMatch(
                        datasource_id=datasource_id,
                        table_name=table_name,
                        columns=[],
                        reason="matched semantic registry",
                        confidence=0.7,
                    )
                )
                seen.add(table_name)
                continue
            first = catalog_columns[0]
            matches.append(
                CatalogSearchMatch(
                    datasource_id=datasource_id,
                    schema_name=first.schema_name,
                    table_name=table_name,
                    columns=[
                        CatalogSearchColumn(
                            name=column.column_name,
                            data_type=column.data_type,
                            nullable=column.nullable,
                            reason="included from semantic table hint",
                        )
                        for column in catalog_columns[:5]
                    ],
                    reason="matched semantic registry",
                    confidence=0.75,
                )
            )
            seen.add(table_name)
        return sorted(matches, key=lambda item: (-item.confidence, item.table_name))[:limit]

    def _semantic_table_hints(self, semantic: SemanticSearchResult) -> list[str]:
        tables: list[str] = []
        for metric in semantic.metrics:
            if metric.recommended_table:
                tables.append(metric.recommended_table)
        for term in semantic.business_terms:
            tables.extend(term.related_tables)
        for mart in semantic.marts:
            tables.append(mart.table_name)
        return list(dict.fromkeys(tables))

    def _matches(self, query: str, values: list[object]) -> bool:
        haystack = " ".join(str(value or "") for value in values).lower().replace("_", " ")
        tokens = self._query_tokens(query)
        return any(token in haystack for token in tokens)

    def _query_tokens(self, query: str) -> list[str]:
        normalized = query.lower().replace("_", " ")
        tokens = [token for token in normalized.split() if token]
        for keyword, expansions in QUERY_SYNONYMS.items():
            if keyword in normalized:
                tokens.extend(expansions)
        return list(dict.fromkeys(tokens))

    def _dialect_capabilities(self, datasource_id: str) -> DatasourceDialectCapabilities | None:
        if self.dialect_capabilities_provider is None:
            return None
        return self.dialect_capabilities_provider(datasource_id)

    def _query_guidance(self, capabilities: DatasourceDialectCapabilities | None) -> list[str]:
        if capabilities is None:
            return []
        guidance = list(capabilities.safe_query_notes)
        guidance.extend(f"For {capabilities.dialect} date differences, use {example}." for example in capabilities.date_diff_examples)
        if capabilities.unsupported_functions:
            blocked = ", ".join(capabilities.unsupported_functions)
            guidance.append(f"Do not use unsupported {capabilities.dialect} functions: {blocked}.")
        return guidance
