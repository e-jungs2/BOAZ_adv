from __future__ import annotations

from fastapi.testclient import TestClient

from data_agent_backend.api import create_app
from data_agent_backend.mcp.tools_analysis_context import (
    analysis_build_context_impl,
    analysis_catalog_search_impl,
    analysis_load_semantic_seed_impl,
    analysis_profile_datasource_impl,
    analysis_upsert_business_term_impl,
    analysis_upsert_column_profile_impl,
    analysis_upsert_join_path_impl,
    analysis_upsert_mart_impl,
    analysis_upsert_metric_impl,
    analysis_upsert_table_profile_impl,
)
from data_agent_backend.models.analysis_context import (
    BusinessTerm,
    ColumnProfile,
    DatasourceProfileResult,
    JoinPath,
    MartDefinition,
    MetricDefinition,
    TableProfile,
)
from data_agent_backend.models.contexts import PolicyContext
from data_agent_backend.models.datasources import DatasourceCatalogColumn, DatasourceCreateRequest
from data_agent_backend.models.datasources import DatasourceKind
from data_agent_backend.services.connectors import ConnectionConfig
from data_agent_backend.services.profile_inference import ProfileInferenceEngine


def create_datasource_with_catalog(services) -> str:
    datasource = services.datasource_service.create_datasource(
        DatasourceCreateRequest(
            name="analytics mysql",
            host="127.0.0.1",
            database="analytics",
            username="reader",
            password="secret",
        ),
        PolicyContext(user_id="u1"),
    )
    services.datasource_registry.replace_catalog(
        datasource.datasource_id,
        [
            DatasourceCatalogColumn(
                datasource_id=datasource.datasource_id,
                schema_name="analytics",
                table_name="orders",
                column_name="order_id",
                data_type="varchar",
                nullable=False,
                ordinal_position=1,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource.datasource_id,
                schema_name="analytics",
                table_name="orders",
                column_name="order_purchase_timestamp",
                data_type="varchar",
                nullable=True,
                ordinal_position=2,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource.datasource_id,
                schema_name="analytics",
                table_name="order_reviews",
                column_name="review_score",
                data_type="int",
                nullable=True,
                ordinal_position=1,
            ),
        ],
    )
    return datasource.datasource_id


def seed_analysis_context(services, datasource_id: str) -> None:
    services.analysis_profile_store.upsert_table_profile(
        TableProfile(
            datasource_id=datasource_id,
            schema_name="analytics",
            table_name="orders",
            row_count=100_000,
            table_type="raw",
            description="Order facts with purchase and delivery timestamps.",
            primary_date_column="order_purchase_timestamp",
        )
    )
    services.analysis_profile_store.upsert_column_profile(
        ColumnProfile(
            datasource_id=datasource_id,
            schema_name="analytics",
            table_name="orders",
            column_name="order_purchase_timestamp",
            semantic_type="datetime_string",
            description="Purchase timestamp stored as a string.",
            null_ratio=0.01,
            distinct_count=90_000,
            sample_values=["2018-01-01 10:00:00", "2018-01-02 11:30:00"],
        )
    )
    services.semantic_registry.upsert_metric(
        MetricDefinition(
            datasource_id=datasource_id,
            name="review_score",
            description="리뷰 점수. Customer review score after delivery.",
            expression="AVG(order_reviews.review_score)",
            recommended_table="order_reviews",
            dimensions=["order_id"],
        )
    )
    services.semantic_registry.upsert_business_term(
        BusinessTerm(
            datasource_id=datasource_id,
            term="배송 지연",
            description="Delivered date later than estimated delivery date.",
            related_tables=["orders"],
            related_columns=["order_delivered_customer_date", "order_estimated_delivery_date"],
            related_metrics=["delivery_delay_days"],
        )
    )
    services.semantic_registry.upsert_mart(
        MartDefinition(
            datasource_id=datasource_id,
            table_name="mart_order_delivery",
            description="Curated order delivery mart for delivery delay analysis.",
            grain="one row per order",
            date_column="order_purchase_date",
            priority=10,
            related_metrics=["delivery_delay_days", "review_score"],
        )
    )
    services.semantic_registry.upsert_join_path(
        JoinPath(
            datasource_id=datasource_id,
            left_table="orders",
            right_table="order_reviews",
            join_condition="orders.order_id = order_reviews.order_id",
            relationship_type="one_to_one_optional",
            confidence=0.9,
        )
    )


def test_analysis_context_combines_catalog_profiles_semantics_and_join_paths(services):
    datasource_id = create_datasource_with_catalog(services)
    seed_analysis_context(services, datasource_id)

    context = services.analysis_context_service.build_analysis_context(
        datasource_id=datasource_id,
        question="배송 지연이 리뷰 점수에 영향이 있는지 분석해줘",
        limit=10,
    )

    assert context.datasource_id == datasource_id
    assert {match.table_name for match in context.catalog_matches} >= {"orders", "order_reviews"}
    assert context.table_profiles[0].table_name == "orders"
    assert context.column_profiles[0].column_name == "order_purchase_timestamp"
    assert [metric.name for metric in context.metrics] == ["review_score"]
    assert [term.term for term in context.business_terms] == ["배송 지연"]
    assert [mart.table_name for mart in context.marts] == ["mart_order_delivery"]
    assert context.join_paths[0].join_condition == "orders.order_id = order_reviews.order_id"
    assert context.usage_notes


def test_analysis_context_expands_korean_question_and_includes_dialect_guidance(services):
    datasource_id = create_datasource_with_catalog(services)

    context = services.analysis_context_service.build_analysis_context(
        datasource_id=datasource_id,
        question="배송은 빠르지만 리뷰는 낮은 주문의 특징은 뭐야?",
        limit=10,
    )

    matched_tables = {match.table_name for match in context.catalog_matches}
    assert {"orders", "order_reviews"} <= matched_tables
    assert context.dialect_capabilities is not None
    assert context.dialect_capabilities.dialect == "mysql"
    assert "julianday" in context.dialect_capabilities.unsupported_functions
    assert any("TIMESTAMPDIFF" in example for example in context.dialect_capabilities.date_diff_examples)
    assert any("TIMESTAMPDIFF" in note for note in context.query_guidance)


def test_context_pack_v2_recommends_tables_columns_hints_and_warnings(services):
    datasource_id = create_datasource_with_catalog(services)
    services.datasource_registry.replace_catalog(
        datasource_id,
        [
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="orders",
                column_name="order_id",
                data_type="text",
                nullable=True,
                ordinal_position=1,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="orders",
                column_name="customer_id",
                data_type="text",
                nullable=True,
                ordinal_position=2,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="orders",
                column_name="order_delivered_carrier_date",
                data_type="text",
                nullable=True,
                ordinal_position=3,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="orders",
                column_name="order_delivered_customer_date",
                data_type="text",
                nullable=True,
                ordinal_position=4,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="orders",
                column_name="order_estimated_delivery_date",
                data_type="text",
                nullable=True,
                ordinal_position=5,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="order_reviews",
                column_name="order_id",
                data_type="text",
                nullable=True,
                ordinal_position=1,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="order_reviews",
                column_name="review_score",
                data_type="bigint",
                nullable=True,
                ordinal_position=2,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="order_items",
                column_name="order_id",
                data_type="text",
                nullable=True,
                ordinal_position=1,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="order_items",
                column_name="product_id",
                data_type="text",
                nullable=True,
                ordinal_position=2,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="order_items",
                column_name="seller_id",
                data_type="text",
                nullable=True,
                ordinal_position=3,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="order_items",
                column_name="price",
                data_type="double",
                nullable=True,
                ordinal_position=4,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="olist",
                table_name="order_items",
                column_name="freight_value",
                data_type="double",
                nullable=True,
                ordinal_position=5,
            ),
        ],
    )

    context = services.analysis_context_service.build_analysis_context(
        datasource_id=datasource_id,
        question="배송은 빠르지만 리뷰는 낮은 주문의 특징은 뭐야?",
        limit=10,
    )

    recommended_tables = {table.table_name for table in context.recommended_tables}
    assert {"orders", "order_reviews", "order_items"} <= recommended_tables

    recommended_columns = {(column.table_name, column.column_name) for column in context.recommended_columns}
    assert ("order_reviews", "review_score") in recommended_columns
    assert ("orders", "order_delivered_carrier_date") in recommended_columns
    assert ("orders", "order_delivered_customer_date") in recommended_columns
    assert ("orders", "order_estimated_delivery_date") in recommended_columns
    assert ("order_items", "price") in recommended_columns
    assert ("order_items", "freight_value") in recommended_columns

    assert any("TIMESTAMPDIFF" in hint.expression_hint for hint in context.time_filter_hints)
    assert any(hint.name == "review_score" for hint in context.metric_hints)
    assert any(hint.left_table == "orders" and hint.right_table == "order_reviews" for hint in context.join_hints)

    warning_codes = {warning.code for warning in context.analysis_warnings}
    assert "profile_missing" in warning_codes
    assert "join_unverified" in warning_codes
    assert "grain_risk" in warning_codes


def test_context_pack_v2_includes_semantic_related_columns(services):
    datasource_id = create_datasource_with_catalog(services)
    services.datasource_registry.replace_catalog(
        datasource_id,
        [
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="orders",
                column_name="order_id",
                data_type="text",
                nullable=False,
                ordinal_position=1,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="orders",
                column_name="customer_id",
                data_type="text",
                nullable=True,
                ordinal_position=2,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="orders",
                column_name="created_at",
                data_type="datetime",
                nullable=True,
                ordinal_position=3,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="orders",
                column_name="status",
                data_type="text",
                nullable=True,
                ordinal_position=4,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="orders",
                column_name="gross_margin",
                data_type="decimal",
                nullable=True,
                ordinal_position=5,
            ),
        ],
    )
    services.semantic_registry.upsert_business_term(
        BusinessTerm(
            datasource_id=datasource_id,
            term="수익성",
            description="주문별 이익률 분석",
            related_tables=["orders"],
            related_columns=["gross_margin"],
        )
    )

    context = services.analysis_context_service.build_analysis_context(
        datasource_id=datasource_id,
        question="수익성 좋은 주문을 분석해줘",
        limit=10,
    )

    recommended_columns = {(column.table_name, column.column_name) for column in context.recommended_columns}
    assert ("orders", "gross_margin") in recommended_columns


def test_context_pack_v2_includes_fallback_mart_date_column(services):
    datasource_id = create_datasource_with_catalog(services)
    services.datasource_registry.replace_catalog(
        datasource_id,
        [
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="mart_sales",
                column_name="order_count",
                data_type="int",
                nullable=True,
                ordinal_position=1,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="mart_sales",
                column_name="gross_amount",
                data_type="decimal",
                nullable=True,
                ordinal_position=2,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="mart_sales",
                column_name="net_amount",
                data_type="decimal",
                nullable=True,
                ordinal_position=3,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="mart_sales",
                column_name="sales_channel",
                data_type="text",
                nullable=True,
                ordinal_position=4,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="mart_sales",
                column_name="region_name",
                data_type="text",
                nullable=True,
                ordinal_position=5,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="mart_sales",
                column_name="paid_at",
                data_type="datetime",
                nullable=True,
                ordinal_position=6,
            ),
        ],
    )
    services.semantic_registry.upsert_mart(
        MartDefinition(
            datasource_id=datasource_id,
            table_name="mart_sales",
            date_column="paid_at",
            priority=30,
        )
    )

    context = services.analysis_context_service.build_analysis_context(
        datasource_id=datasource_id,
        question="매출 마트로 분석해줘",
        limit=10,
    )

    assert any(mart.table_name == "mart_sales" for mart in context.marts)
    recommended_columns = {(column.table_name, column.column_name) for column in context.recommended_columns}
    assert ("mart_sales", "paid_at") in recommended_columns


def test_context_pack_v2_includes_qualified_metric_dimension_table(services):
    datasource_id = create_datasource_with_catalog(services)
    services.datasource_registry.replace_catalog(
        datasource_id,
        [
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="orders",
                column_name="order_id",
                data_type="text",
                nullable=False,
                ordinal_position=1,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="customers",
                column_name="customer_id",
                data_type="text",
                nullable=False,
                ordinal_position=1,
            ),
            DatasourceCatalogColumn(
                datasource_id=datasource_id,
                schema_name="analytics",
                table_name="customers",
                column_name="state",
                data_type="text",
                nullable=True,
                ordinal_position=2,
            ),
        ],
    )
    services.semantic_registry.upsert_metric(
        MetricDefinition(
            datasource_id=datasource_id,
            name="regional_order_count",
            description="Regional order count metric.",
            expression="COUNT(DISTINCT orders.order_id)",
            recommended_table="orders",
            dimensions=["customers.state"],
        )
    )

    context = services.analysis_context_service.build_analysis_context(
        datasource_id=datasource_id,
        question="regional_order_count 분석해줘",
        limit=10,
    )

    recommended_tables = {table.table_name for table in context.recommended_tables}
    assert "customers" in recommended_tables
    recommended_columns = {(column.table_name, column.column_name) for column in context.recommended_columns}
    assert ("customers", "state") in recommended_columns


def test_analysis_context_mcp_tools_return_tool_result_envelope(services):
    datasource_id = create_datasource_with_catalog(services)

    table_profile = analysis_upsert_table_profile_impl(
        datasource_id=datasource_id,
        table_name="orders",
        schema_name="analytics",
        row_count=100_000,
        table_type="raw",
        description="Order facts.",
        primary_date_column="order_purchase_timestamp",
        services=services,
    )
    assert table_profile.ok is True
    assert table_profile.data["table_name"] == "orders"

    column_profile = analysis_upsert_column_profile_impl(
        datasource_id=datasource_id,
        table_name="orders",
        column_name="order_purchase_timestamp",
        schema_name="analytics",
        semantic_type="datetime_string",
        sample_values=["2018-01-01 10:00:00"],
        services=services,
    )
    assert column_profile.ok is True

    metric = analysis_upsert_metric_impl(
        datasource_id=datasource_id,
        name="review_score",
        description="Customer review score.",
        expression="AVG(order_reviews.review_score)",
        recommended_table="order_reviews",
        services=services,
    )
    assert metric.ok is True

    term = analysis_upsert_business_term_impl(
        datasource_id=datasource_id,
        term="배송 지연",
        description="Delivery delay.",
        related_tables=["orders"],
        services=services,
    )
    assert term.ok is True

    mart = analysis_upsert_mart_impl(
        datasource_id=datasource_id,
        table_name="mart_order_delivery",
        description="Delivery mart.",
        grain="one row per order",
        date_column="order_purchase_date",
        priority=10,
        related_metrics=["review_score"],
        services=services,
    )
    assert mart.ok is True

    join = analysis_upsert_join_path_impl(
        datasource_id=datasource_id,
        left_table="orders",
        right_table="order_reviews",
        join_condition="orders.order_id = order_reviews.order_id",
        relationship_type="one_to_one_optional",
        confidence=0.9,
        services=services,
    )
    assert join.ok is True

    search = analysis_catalog_search_impl(datasource_id=datasource_id, query="review score", services=services)
    assert search.ok is True
    assert search.data["matches"][0]["table_name"] == "order_reviews"

    context = analysis_build_context_impl(datasource_id=datasource_id, question="배송 지연 리뷰 점수", services=services)
    assert context.ok is True
    assert context.data["marts"][0]["table_name"] == "mart_order_delivery"
    assert "recommended_tables" in context.data
    assert "recommended_columns" in context.data
    assert "analysis_warnings" in context.data


def test_analysis_context_http_routes_use_tool_result_envelope(services):
    datasource_id = create_datasource_with_catalog(services)
    client = TestClient(create_app(services))

    upserted = client.post(
        f"/analysis-context/{datasource_id}/table-profiles",
        json={
            "schema_name": "analytics",
            "table_name": "orders",
            "row_count": 100000,
            "table_type": "raw",
            "description": "Order facts.",
            "primary_date_column": "order_purchase_timestamp",
        },
    ).json()
    assert upserted["ok"] is True
    assert upserted["data"]["table_name"] == "orders"

    metric = client.post(
        f"/analysis-context/{datasource_id}/metrics",
        json={
            "name": "review_score",
            "description": "리뷰 점수. Customer review score.",
            "expression": "AVG(order_reviews.review_score)",
            "recommended_table": "order_reviews",
        },
    ).json()
    assert metric["ok"] is True

    searched = client.post(f"/analysis-context/{datasource_id}/catalog-search", json={"query": "review score"}).json()
    assert searched["ok"] is True
    assert searched["data"]["matches"][0]["table_name"] == "order_reviews"

    context = client.post(f"/analysis-context/{datasource_id}/context", json={"question": "리뷰 점수 분석"}).json()
    assert context["ok"] is True
    assert context["data"]["metrics"][0]["name"] == "review_score"
    assert "recommended_tables" in context["data"]
    assert "recommended_columns" in context["data"]
    assert "analysis_warnings" in context["data"]


class ProfilingConnector:
    def test_connection(self, config: ConnectionConfig) -> dict:
        return {"server_reachable": True}

    def introspect(self, datasource_id: str, config: ConnectionConfig) -> list[DatasourceCatalogColumn]:
        return []

    def execute_query(self, config: ConnectionConfig, query: str, row_limit: int):
        raise AssertionError("profile_datasource should use connector profile_tables when available")

    def profile_tables(
        self,
        config: ConnectionConfig,
        datasource_id: str,
        catalog: list[DatasourceCatalogColumn],
        table_names: list[str] | None = None,
        sample_limit: int = 20,
    ) -> DatasourceProfileResult:
        return DatasourceProfileResult(
            datasource_id=datasource_id,
            table_profiles=[
                TableProfile(
                    datasource_id=datasource_id,
                    schema_name="analytics",
                    table_name="orders",
                    row_count=1234,
                    table_type="raw",
                    description="Profiled by connector.",
                    primary_date_column="order_purchase_timestamp",
                    metadata={"profile": {"strategy": "limit", "sample_limit": sample_limit}},
                )
            ],
            column_profiles=[
                ColumnProfile(
                    datasource_id=datasource_id,
                    schema_name="analytics",
                    table_name="orders",
                    column_name="order_purchase_timestamp",
                    semantic_type="datetime_string",
                    sample_values=["2018-01-01 10:00:00"],
                    metadata={"field_sources": {"sample_values": "sample"}, "profile": {"strategy": "limit", "sample_limit": sample_limit}},
                )
            ],
            usage_notes=["Connector profile collected."],
        )


def test_profile_datasource_persists_connector_profiles(services):
    datasource_id = create_datasource_with_catalog(services)
    services.datasource_service.connectors = {DatasourceKind.mysql: ProfilingConnector()}

    result = analysis_profile_datasource_impl(
        datasource_id=datasource_id,
        table_names=["orders"],
        sample_limit=3,
        services=services,
    )

    assert result.ok is True
    assert result.data["table_profiles"][0]["row_count"] == 1234
    assert services.analysis_profile_store.get_table_profile(datasource_id, "orders").row_count == 1234
    assert services.analysis_profile_store.get_column_profile(datasource_id, "orders", "order_purchase_timestamp").sample_values == [
        "2018-01-01 10:00:00"
    ]


def test_inferred_profile_upsert_preserves_manual_field_sources(services):
    datasource_id = create_datasource_with_catalog(services)
    services.analysis_profile_store.upsert_table_profile(
        TableProfile(
            datasource_id=datasource_id,
            schema_name="analytics",
            table_name="orders",
            row_count=100,
            table_type="raw",
            primary_date_column="paid_at",
            metadata={"field_sources": {"primary_date_column": "manual"}},
        )
    )

    services.analysis_profile_store.upsert_table_profile(
        TableProfile(
            datasource_id=datasource_id,
            schema_name="analytics",
            table_name="orders",
            row_count=200,
            table_type="raw",
            primary_date_column="created_at",
            metadata={"field_sources": {"primary_date_column": "inferred", "row_count": "catalog"}},
        )
    )

    stored = services.analysis_profile_store.get_table_profile(datasource_id, "orders")
    assert stored.primary_date_column == "paid_at"
    assert stored.row_count == 200
    assert stored.metadata["field_sources"]["primary_date_column"] == "manual"
    assert stored.metadata["field_sources"]["row_count"] == "catalog"


def test_inferred_semantic_upsert_preserves_manual_join_and_mart_records(services):
    datasource_id = create_datasource_with_catalog(services)
    services.semantic_registry.upsert_mart(
        MartDefinition(
            datasource_id=datasource_id,
            table_name="mart_order_delivery",
            date_column="paid_at",
            priority=99,
            metadata={"field_sources": {"date_column": "manual", "priority": "manual"}},
        )
    )
    services.semantic_registry.upsert_mart(
        MartDefinition(
            datasource_id=datasource_id,
            table_name="mart_order_delivery",
            date_column="created_at",
            priority=30,
            metadata={"field_sources": {"date_column": "inferred", "priority": "inferred"}},
        )
    )

    manual = JoinPath(
        datasource_id=datasource_id,
        left_table="orders",
        right_table="customers",
        join_condition="orders.customer_id = customers.customer_unique_id",
        relationship_type="many_to_one",
        confidence=0.95,
        metadata={"field_sources": {"join_condition": "manual", "confidence": "manual"}},
    )
    services.semantic_registry.upsert_join_path(manual)
    services.semantic_registry.upsert_join_path(
        manual.model_copy(
            update={
                "join_condition": "orders.customer_id = customers.customer_id",
                "confidence": 0.7,
                "metadata": {"field_sources": {"join_condition": "inferred", "confidence": "inferred"}},
            }
        )
    )

    mart = services.semantic_registry.list_marts(datasource_id)[0]
    joins = services.semantic_registry.get_join_paths(datasource_id, ["orders", "customers"])
    assert mart.date_column == "paid_at"
    assert mart.priority == 99
    assert any(join.join_condition == "orders.customer_id = customers.customer_unique_id" and join.confidence == 0.95 for join in joins)


class InferredSemanticConnector(ProfilingConnector):
    def profile_tables(
        self,
        config: ConnectionConfig,
        datasource_id: str,
        catalog: list[DatasourceCatalogColumn],
        table_names: list[str] | None = None,
        sample_limit: int = 20,
    ) -> DatasourceProfileResult:
        result = super().profile_tables(config, datasource_id, catalog, table_names, sample_limit)
        return result.model_copy(
            update={
                "marts": [
                    MartDefinition(
                        datasource_id=datasource_id,
                        table_name="mart_order_summary",
                        date_column="order_date",
                        priority=30,
                        metadata={"field_sources": {"table_name": "inferred", "priority": "inferred"}},
                    )
                ],
                "join_paths": [
                    JoinPath(
                        datasource_id=datasource_id,
                        left_table="customers",
                        right_table="orders",
                        join_condition="customers.customer_id = orders.customer_id",
                        relationship_type="candidate",
                        confidence=0.75,
                        metadata={"field_sources": {"join_condition": "inferred", "confidence": "inferred"}},
                    )
                ],
            }
        )


def test_profile_datasource_persists_inferred_marts_and_join_paths(services):
    datasource_id = create_datasource_with_catalog(services)
    services.datasource_service.connectors = {DatasourceKind.mysql: InferredSemanticConnector()}

    result = analysis_profile_datasource_impl(datasource_id=datasource_id, services=services)

    assert result.ok is True
    marts = services.semantic_registry.list_marts(datasource_id)
    joins = services.semantic_registry.get_join_paths(datasource_id, ["orders", "customers"])
    assert [mart.table_name for mart in marts] == ["mart_order_summary"]
    assert any("customer_id" in join.join_condition for join in joins)


def test_load_semantic_seed_persists_metrics_terms_marts_and_join_paths(services):
    datasource_id = create_datasource_with_catalog(services)

    loaded = analysis_load_semantic_seed_impl(
        datasource_id=datasource_id,
        seed={
            "metrics": [
                {
                    "name": "delivery_delay_days",
                    "description": "배송 지연 일수",
                    "expression": "DATEDIFF(order_delivered_customer_date, order_estimated_delivery_date)",
                    "recommended_table": "mart_order_delivery",
                }
            ],
            "business_terms": [
                {
                    "term": "배송 지연",
                    "description": "예상 배송일보다 늦게 배송된 주문",
                    "related_tables": ["orders"],
                    "related_metrics": ["delivery_delay_days"],
                }
            ],
            "marts": [
                {
                    "table_name": "mart_order_delivery",
                    "description": "배송 분석용 mart",
                    "grain": "one row per order",
                    "date_column": "order_purchase_date",
                    "priority": 20,
                    "related_metrics": ["delivery_delay_days"],
                }
            ],
            "join_paths": [
                {
                    "left_table": "orders",
                    "right_table": "order_reviews",
                    "join_condition": "orders.order_id = order_reviews.order_id",
                    "relationship_type": "one_to_one_optional",
                    "confidence": 0.9,
                }
            ],
        },
        services=services,
    )

    assert loaded.ok is True
    assert loaded.data == {"metrics": 1, "business_terms": 1, "marts": 1, "join_paths": 1}
    context = services.analysis_context_service.build_analysis_context(datasource_id, "배송 지연 분석")
    assert context.metrics[0].name == "delivery_delay_days"
    assert context.marts[0].table_name == "mart_order_delivery"
    assert context.join_paths[0].join_condition == "orders.order_id = order_reviews.order_id"


def test_sample_profile_inference_builds_table_and_column_profiles():
    columns = [
        DatasourceCatalogColumn(
            datasource_id="ds_1",
            schema_name="analytics",
            table_name="orders",
            column_name="order_id",
            data_type="varchar",
            nullable=False,
            ordinal_position=1,
        ),
        DatasourceCatalogColumn(
            datasource_id="ds_1",
            schema_name="analytics",
            table_name="orders",
            column_name="customer_id",
            data_type="varchar",
            nullable=True,
            ordinal_position=2,
        ),
        DatasourceCatalogColumn(
            datasource_id="ds_1",
            schema_name="analytics",
            table_name="orders",
            column_name="order_purchase_timestamp",
            data_type="varchar",
            nullable=True,
            ordinal_position=3,
        ),
        DatasourceCatalogColumn(
            datasource_id="ds_1",
            schema_name="analytics",
            table_name="orders",
            column_name="amount",
            data_type="decimal",
            nullable=True,
            ordinal_position=4,
        ),
    ]
    sample_rows = [
        {
            "order_id": "o1",
            "customer_id": "c1",
            "order_purchase_timestamp": "2018-01-01 10:00:00",
            "amount": "12.50",
        },
        {
            "order_id": "o2",
            "customer_id": "c2",
            "order_purchase_timestamp": "2018-01-02 11:00:00",
            "amount": "20.00",
        },
    ]

    engine = ProfileInferenceEngine()
    result = engine.infer_table("ds_1", "analytics", "orders", columns, sample_rows, sample_limit=20)

    assert result.table_profile.table_name == "orders"
    assert result.table_profile.primary_date_column == "order_purchase_timestamp"
    assert result.table_profile.table_type == "raw"
    assert result.table_profile.metadata["profile"]["strategy"] == "limit"
    assert result.table_profile.metadata["profile"]["sample_limit"] == 20

    profiles = {profile.column_name: profile for profile in result.column_profiles}
    assert profiles["order_id"].semantic_type == "identifier"
    assert profiles["customer_id"].semantic_type == "foreign_key"
    assert profiles["order_purchase_timestamp"].semantic_type == "datetime_string"
    assert profiles["amount"].semantic_type == "measure"
    assert profiles["amount"].sample_values == ["12.50", "20.00"]
    assert profiles["amount"].null_ratio is None
    assert profiles["amount"].distinct_count is None


def test_sample_profile_inference_builds_join_and_mart_candidates():
    customer_columns = [
        DatasourceCatalogColumn(
            datasource_id="ds_1",
            schema_name="analytics",
            table_name="customers",
            column_name="customer_id",
            data_type="varchar",
            nullable=False,
            ordinal_position=1,
        ),
        DatasourceCatalogColumn(
            datasource_id="ds_1",
            schema_name="analytics",
            table_name="customers",
            column_name="customer_name",
            data_type="varchar",
            nullable=True,
            ordinal_position=2,
        ),
    ]
    order_columns = [
        DatasourceCatalogColumn(
            datasource_id="ds_1",
            schema_name="analytics",
            table_name="orders",
            column_name="order_id",
            data_type="varchar",
            nullable=False,
            ordinal_position=1,
        ),
        DatasourceCatalogColumn(
            datasource_id="ds_1",
            schema_name="analytics",
            table_name="orders",
            column_name="customer_id",
            data_type="varchar",
            nullable=True,
            ordinal_position=2,
        ),
    ]
    mart_columns = [
        DatasourceCatalogColumn(
            datasource_id="ds_1",
            schema_name="analytics",
            table_name="mart_order_summary",
            column_name="order_date",
            data_type="date",
            nullable=True,
            ordinal_position=1,
        ),
        DatasourceCatalogColumn(
            datasource_id="ds_1",
            schema_name="analytics",
            table_name="mart_order_summary",
            column_name="order_count",
            data_type="int",
            nullable=True,
            ordinal_position=2,
        ),
    ]
    customer_rows = [{"customer_id": "c1", "customer_name": "Alice"}]
    order_rows = [{"order_id": "o1", "customer_id": "c1"}]
    mart_rows = [{"order_date": "2018-01-01", "order_count": 10}]

    engine = ProfileInferenceEngine()
    orders = engine.infer_table("ds_1", "analytics", "orders", order_columns, order_rows, sample_limit=20)
    customers = engine.infer_table("ds_1", "analytics", "customers", customer_columns, customer_rows, sample_limit=20)
    mart = engine.infer_table("ds_1", "analytics", "mart_order_summary", mart_columns, mart_rows, sample_limit=20)
    joins = engine.infer_join_paths(
        "ds_1",
        [orders, customers, mart],
        {
            "orders": order_columns,
            "customers": customer_columns,
            "mart_order_summary": mart_columns,
        },
        {
            "orders": order_rows,
            "customers": customer_rows,
            "mart_order_summary": mart_rows,
        },
        sample_limit=20,
    )

    assert any(join.join_condition == "customers.customer_id = orders.customer_id" for join in joins)
    assert mart.table_profile.table_type == "mart"
    assert mart.marts[0].table_name == "mart_order_summary"
    assert mart.marts[0].priority == 30
