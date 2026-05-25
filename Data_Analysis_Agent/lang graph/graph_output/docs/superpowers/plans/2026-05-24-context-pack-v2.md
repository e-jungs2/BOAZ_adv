# Context Pack v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `build_analysis_context`가 Agent에게 추천 테이블, 컬럼, 조인, 시간 계산, 지표, 경고를 구조화해서 반환하도록 Context Pack v2를 구현한다.

**Architecture:** 기존 `AnalysisContextService.build_analysis_context()` 흐름을 유지하고, 기존 context 필드에 additive field를 추가한다. 새 추천 필드는 catalog, semantic registry, 저장된 profile, dialect capabilities만 사용하며, 실제 DB sampling query나 Profile Bootstrap은 실행하지 않는다.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI/MCP 공통 `ToolResult`, pytest, uv.

---

## 파일 구조

- 수정: `src/data_agent_backend/models/analysis_context.py`
  - Context Pack v2 응답 모델과 `AnalysisContext` 신규 필드를 정의한다.
- 수정: `src/data_agent_backend/services/analysis_context_service.py`
  - catalog/profile/semantic/dialect 정보를 조합해 추천 필드를 생성한다.
- 수정: `tests/test_analysis_context.py`
  - 실행 로그 질문을 기반으로 Context Pack v2 회귀 테스트를 추가한다.

이번 계획은 `src/data_agent_backend/services/datasource_service.py`, connector, HTTP router, MCP wrapper를 수정하지 않는다. `AnalysisContext`에 새 필드를 기본 빈 list로 추가하는 additive change이므로 기존 HTTP/MCP envelope는 그대로 동작해야 한다.

## 전제 조건

현재 작업 트리에는 이미 dialect-aware context 보강 변경이 있다.

- `DatasourceDialectCapabilities`
- connector `dialect_capabilities()`
- MySQL `TIMESTAMPDIFF` guidance
- `AnalysisContext.dialect_capabilities`
- `AnalysisContext.query_guidance`
- 한국어 질문 token 확장

이 변경은 되돌리지 않는다. Context Pack v2는 해당 변경 위에 쌓는다.

---

### Task 1: Context Pack v2 회귀 테스트 추가

**Files:**
- Modify: `tests/test_analysis_context.py`

- [ ] **Step 1: Write the failing test**

`tests/test_analysis_context.py`의 기존 `test_analysis_context_expands_korean_question_and_includes_dialect_guidance` 아래에 다음 테스트를 추가한다.

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_context_pack_v2_recommends_tables_columns_hints_and_warnings -q
```

Expected: FAIL with `AttributeError` or Pydantic field access failure because `AnalysisContext` does not yet expose `recommended_tables`, `recommended_columns`, `join_hints`, `time_filter_hints`, `metric_hints`, and `analysis_warnings`.

---

### Task 2: Context Pack v2 response models 추가

**Files:**
- Modify: `src/data_agent_backend/models/analysis_context.py`
- Test: `tests/test_analysis_context.py`

- [ ] **Step 1: Add model classes and fields**

`src/data_agent_backend/models/analysis_context.py`에 다음 모델을 추가하고 `AnalysisContext`에 신규 필드를 추가한다.

```python
class RecommendedTable(BackendModel):
    table_name: str
    schema_name: str | None = None
    reason: str
    confidence: float = 0.0
    source: str = "catalog"
    warnings: list[str] = []


class RecommendedColumn(BackendModel):
    table_name: str
    column_name: str
    schema_name: str | None = None
    data_type: str
    semantic_type: str | None = None
    role: str
    reason: str
    confidence: float = 0.0


class JoinHint(BackendModel):
    left_table: str
    right_table: str
    join_condition: str
    relationship_type: str | None = None
    confidence: float = 0.0
    source: str = "catalog_inferred"
    warnings: list[str] = []


class TimeFilterHint(BackendModel):
    name: str
    table_name: str
    column_names: list[str]
    expression_hint: str
    dialect: str | None = None
    reason: str


class MetricHint(BackendModel):
    name: str
    expression_hint: str
    table_name: str | None = None
    column_names: list[str] = []
    reason: str
    source: str = "catalog"


class AnalysisWarning(BackendModel):
    code: str
    message: str
    severity: str = "info"
    details: JsonDict = {}
```

`AnalysisContext`에는 다음 필드를 추가한다.

```python
class AnalysisContext(BackendModel):
    datasource_id: str
    question: str
    catalog_matches: list[CatalogSearchMatch] = []
    table_profiles: list[TableProfile] = []
    column_profiles: list[ColumnProfile] = []
    metrics: list[MetricDefinition] = []
    business_terms: list[BusinessTerm] = []
    marts: list[MartDefinition] = []
    join_paths: list[JoinPath] = []
    dialect_capabilities: DatasourceDialectCapabilities | None = None
    query_guidance: list[str] = []
    recommended_tables: list[RecommendedTable] = []
    recommended_columns: list[RecommendedColumn] = []
    join_hints: list[JoinHint] = []
    time_filter_hints: list[TimeFilterHint] = []
    metric_hints: list[MetricHint] = []
    analysis_warnings: list[AnalysisWarning] = []
    usage_notes: list[str] = []
```

- [ ] **Step 2: Run test to verify it still fails later in behavior**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_context_pack_v2_recommends_tables_columns_hints_and_warnings -q
```

Expected: FAIL because fields now exist but `AnalysisContextService.build_analysis_context()` still returns empty lists for the new fields.

---

### Task 3: Recommended tables와 columns 생성

**Files:**
- Modify: `src/data_agent_backend/services/analysis_context_service.py`
- Test: `tests/test_analysis_context.py`

- [ ] **Step 1: Import new models**

`src/data_agent_backend/services/analysis_context_service.py`의 import 목록에 신규 모델을 추가한다.

```python
from data_agent_backend.models.analysis_context import (
    AnalysisContext,
    AnalysisWarning,
    CatalogSearchColumn,
    CatalogSearchMatch,
    CatalogSearchResult,
    ColumnProfile,
    JoinHint,
    MetricHint,
    RecommendedColumn,
    RecommendedTable,
    SemanticSearchResult,
    TableProfile,
    TimeFilterHint,
)
```

- [ ] **Step 2: Add helper methods for recommended tables and columns**

`AnalysisContextService`에 다음 helper를 추가한다.

```python
    def _recommended_tables(
        self,
        matches: list[CatalogSearchMatch],
        table_profiles: list[TableProfile],
    ) -> list[RecommendedTable]:
        profiled = {profile.table_name for profile in table_profiles}
        recommendations: list[RecommendedTable] = []
        for match in matches:
            source = "profile" if match.table_name in profiled else "catalog"
            warnings = [] if match.table_name in profiled else ["No stored table profile is available for this table."]
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
    ) -> list[RecommendedColumn]:
        profile_by_key = {
            (profile.table_name, profile.column_name): profile
            for profile in column_profiles
        }
        recommendations: list[RecommendedColumn] = []
        seen: set[tuple[str, str]] = set()
        for match in matches:
            catalog_columns = self.datasource_registry.get_catalog(match.datasource_id, match.table_name)
            matched_names = {column.name for column in match.columns}
            for column in catalog_columns:
                if matched_names and column.column_name not in matched_names and not self._important_column(column.column_name):
                    continue
                key = (column.table_name, column.column_name)
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
                        reason=f"{role} candidate from catalog match",
                        confidence=0.8 if profile else 0.65,
                    )
                )
                seen.add(key)
        return sorted(recommendations, key=lambda item: (-item.confidence, item.table_name, item.column_name))
```

- [ ] **Step 3: Add column role helpers**

같은 class에 다음 helper를 추가한다.

```python
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
```

- [ ] **Step 4: Wire recommended tables and columns into context**

`build_analysis_context()`에서 `return AnalysisContext(...)` 직전에 다음 값을 만든다.

```python
        recommended_tables = self._recommended_tables(catalog_matches, table_profiles)
        recommended_columns = self._recommended_columns(catalog_matches, column_profiles)
```

그리고 `AnalysisContext(...)`에 전달한다.

```python
            recommended_tables=recommended_tables,
            recommended_columns=recommended_columns,
```

- [ ] **Step 5: Run test and inspect expected partial progress**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_context_pack_v2_recommends_tables_columns_hints_and_warnings -q
```

Expected: FAIL only on `time_filter_hints`, `metric_hints`, `join_hints`, or warning assertions. Recommended table/column assertions should pass.

---

### Task 4: Time filter hints와 metric hints 생성

**Files:**
- Modify: `src/data_agent_backend/services/analysis_context_service.py`
- Test: `tests/test_analysis_context.py`

- [ ] **Step 1: Add time filter helper**

`AnalysisContextService`에 다음 helper를 추가한다.

```python
    def _time_filter_hints(
        self,
        columns: list[RecommendedColumn],
        capabilities: DatasourceDialectCapabilities | None,
    ) -> list[TimeFilterHint]:
        by_table: dict[str, set[str]] = {}
        for column in columns:
            if column.role == "time":
                by_table.setdefault(column.table_name, set()).add(column.column_name)

        hints: list[TimeFilterHint] = []
        dialect = capabilities.dialect if capabilities else None
        if "orders" in by_table:
            order_columns = by_table["orders"]
            if {"order_delivered_carrier_date", "order_delivered_customer_date"} <= order_columns:
                expression = (
                    "TIMESTAMPDIFF(HOUR, order_delivered_carrier_date, order_delivered_customer_date) / 24.0"
                    if dialect == "mysql"
                    else "end_timestamp - start_timestamp"
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
                    else "delivered_timestamp - estimated_timestamp"
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
```

- [ ] **Step 2: Add metric hint helper**

`AnalysisContextService`에 다음 helper를 추가한다.

```python
    def _metric_hints(
        self,
        semantic_metrics: list,
        columns: list[RecommendedColumn],
    ) -> list[MetricHint]:
        hints = [
            MetricHint(
                name=metric.name,
                expression_hint=metric.expression,
                table_name=metric.recommended_table,
                column_names=[],
                reason=metric.description or "semantic registry metric",
                source="semantic",
            )
            for metric in semantic_metrics
        ]
        existing = {hint.name for hint in hints}
        for column in columns:
            if column.role != "metric":
                continue
            metric_name = column.column_name
            if metric_name in existing:
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
            existing.add(metric_name)
        if "order_count" not in existing and any(column.column_name == "order_id" for column in columns):
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
```

- [ ] **Step 3: Wire time and metric hints into context**

`build_analysis_context()`에서 recommended columns 생성 직후 다음 값을 만든다.

```python
        time_filter_hints = self._time_filter_hints(recommended_columns, dialect_capabilities)
        metric_hints = self._metric_hints(semantic.metrics, recommended_columns)
```

그리고 `AnalysisContext(...)`에 전달한다.

```python
            time_filter_hints=time_filter_hints,
            metric_hints=metric_hints,
```

- [ ] **Step 4: Run test and inspect expected partial progress**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_context_pack_v2_recommends_tables_columns_hints_and_warnings -q
```

Expected: FAIL only on `join_hints` or `analysis_warnings` assertions.

---

### Task 5: Join hints와 analysis warnings 생성

**Files:**
- Modify: `src/data_agent_backend/services/analysis_context_service.py`
- Test: `tests/test_analysis_context.py`

- [ ] **Step 1: Add join hint helper**

`AnalysisContextService`에 다음 helper를 추가한다.

```python
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
        table_names = [table.table_name for table in recommended_tables]
        catalog_by_table = {
            table_name: self.datasource_registry.get_catalog(datasource_id, table_name)
            for table_name in table_names
        }
        for left_index, left_table in enumerate(table_names):
            for right_table in table_names[left_index + 1 :]:
                for left in catalog_by_table.get(left_table, []):
                    for right in catalog_by_table.get(right_table, []):
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
```

- [ ] **Step 2: Add warning helper**

`AnalysisContextService`에 다음 helper를 추가한다.

```python
    def _analysis_warnings(
        self,
        recommended_tables: list[RecommendedTable],
        table_profiles: list[TableProfile],
        column_profiles: list[ColumnProfile],
        join_hints: list[JoinHint],
        dialect_capabilities: DatasourceDialectCapabilities | None,
    ) -> list[AnalysisWarning]:
        warnings: list[AnalysisWarning] = []
        if recommended_tables and (not table_profiles or not column_profiles):
            warnings.append(
                AnalysisWarning(
                    code="profile_missing",
                    message="No stored table or column profiles are available for at least one recommended table.",
                    severity="warning",
                    details={"table_names": [table.table_name for table in recommended_tables]},
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
        if recommended_tables and (not table_profiles or not column_profiles):
            warnings.append(
                AnalysisWarning(
                    code="context_partial",
                    message="Context recommendations are based on catalog and semantic hints only.",
                    severity="info",
                    details={},
                )
            )
        return warnings
```

- [ ] **Step 3: Wire join hints and warnings into context**

`build_analysis_context()`에서 metric hints 생성 직후 다음 값을 만든다.

```python
        join_hints = self._join_hints(datasource_id, join_paths, recommended_tables)
        analysis_warnings = self._analysis_warnings(
            recommended_tables,
            table_profiles,
            column_profiles,
            join_hints,
            dialect_capabilities,
        )
```

그리고 `AnalysisContext(...)`에 전달한다.

```python
            join_hints=join_hints,
            analysis_warnings=analysis_warnings,
```

- [ ] **Step 4: Run focused test**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_context_pack_v2_recommends_tables_columns_hints_and_warnings -q
```

Expected: PASS.

---

### Task 6: HTTP/MCP envelope와 기존 context 동작 회귀 확인

**Files:**
- Modify: `tests/test_analysis_context.py`

- [ ] **Step 1: Extend existing MCP envelope test**

`test_analysis_context_mcp_tools_return_tool_result_envelope`의 `context` assertion 뒤에 다음 assertion을 추가한다.

```python
    assert "recommended_tables" in context.data
    assert "recommended_columns" in context.data
    assert "analysis_warnings" in context.data
```

- [ ] **Step 2: Extend existing HTTP route test**

`test_analysis_context_http_routes_use_tool_result_envelope`의 `context` assertion 뒤에 다음 assertion을 추가한다.

```python
    assert "recommended_tables" in context["data"]
    assert "recommended_columns" in context["data"]
    assert "analysis_warnings" in context["data"]
```

- [ ] **Step 3: Run analysis context tests**

Run:

```powershell
uv run pytest tests/test_analysis_context.py -q
```

Expected: PASS.

---

### Task 7: 전체 검증과 커밋

**Files:**
- Verify all modified source and test files

- [ ] **Step 1: Run datasource-related tests**

Run:

```powershell
uv run pytest tests/test_analysis_context.py tests/test_datasources.py -q
```

Expected: PASS, with the existing optional MySQL integration test skipped when `DATA_AGENT_TEST_MYSQL_URL` is not set.

- [ ] **Step 2: Run full suite**

Run:

```powershell
uv run pytest -q
```

Expected: PASS. Current known baseline after dialect-aware changes was `111 passed, 1 skipped`.

- [ ] **Step 3: Inspect diff**

Run:

```powershell
git diff -- src/data_agent_backend/models/analysis_context.py src/data_agent_backend/services/analysis_context_service.py tests/test_analysis_context.py
```

Expected: Diff only contains Context Pack v2 models, recommendation generation helpers, and related tests. It must not introduce Profile Bootstrap, DB sampling, agent prompt rewrites, or new connector behavior.

- [ ] **Step 4: Commit implementation**

Stage only implementation files for this plan plus any already-approved prerequisite changes that should ship together.

```powershell
git add src/data_agent_backend/models/analysis_context.py src/data_agent_backend/services/analysis_context_service.py tests/test_analysis_context.py
git commit -m "Add context pack v2 recommendations"
```

If the dialect-aware prerequisite changes are still uncommitted and should ship in the same branch, include them intentionally in either the same commit or a preceding commit:

```powershell
git add src/data_agent_backend/models/datasources.py src/data_agent_backend/services/connectors/base.py src/data_agent_backend/services/connectors/mysql.py src/data_agent_backend/services/datasource_service.py src/data_agent_backend/services/factory.py tests/test_datasources.py
git commit -m "Add datasource dialect guidance"
```

Do not stage unrelated files.

---

## Self-Review

- Spec coverage: The plan implements all Context Pack v2 fields from the design and explicitly excludes Profile Bootstrap, DB sampling, agent prompt rewrites, and new connectors.
- Placeholder scan: No placeholder markers are present. Every implementation step includes concrete file names, commands, expected outcomes, and code snippets.
- Type consistency: Model names and field names match the design: `RecommendedTable`, `RecommendedColumn`, `JoinHint`, `TimeFilterHint`, `MetricHint`, `AnalysisWarning`, and the corresponding `AnalysisContext` list fields.
