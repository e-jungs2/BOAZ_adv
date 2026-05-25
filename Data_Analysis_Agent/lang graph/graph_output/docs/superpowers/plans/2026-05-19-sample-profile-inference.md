# Sample Profile Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sample-based automatic profile and semantic metadata inference to `data_agent_backend` while preserving manual field-level overrides.

**Architecture:** Keep the existing datasource, profile store, semantic registry, API, and MCP boundaries. Add a deterministic `ProfileInferenceEngine` that consumes catalog columns and limited sample rows, then update store/registry upsert behavior so automatic refreshes do not overwrite fields marked as manual in `metadata.field_sources`.

**Tech Stack:** Python 3.11, Pydantic, SQLite metadata JSON, SQLAlchemy Core engine, FastAPI, MCP tool wrappers, pytest.

---

## File Structure

- Create `src/data_agent_backend/services/profile_inference.py`: pure rule-based inference helpers for table profiles, column profiles, join candidates, and mart candidates.
- Modify `src/data_agent_backend/services/connectors/base.py`: add a typed sample/profile input or result shape only if needed by the inference engine.
- Modify `src/data_agent_backend/services/connectors/mysql.py`: use the inference engine from `profile_tables()` and record sample provenance.
- Modify `src/data_agent_backend/services/datasource_service.py`: persist inferred semantic join paths and mart candidates after profiling.
- Modify `src/data_agent_backend/services/analysis_profile_store.py`: preserve manual field-level overrides during inferred upserts.
- Modify `src/data_agent_backend/services/semantic_registry.py`: preserve manual semantic records during inferred upserts.
- Modify `src/data_agent_backend/models/analysis_context.py`: keep model fields stable; only add lightweight helper types if tests need them.
- Modify `tests/test_analysis_context.py`: add service/API/MCP coverage for sample inference and manual override behavior.
- Modify `tests/test_datasources.py`: add datasource profiling connector behavior tests if the MySQL connector contract changes.

## Backlog

### Task 1: Profile Inference Unit Tests

**Files:**
- Create: `src/data_agent_backend/services/profile_inference.py`
- Modify: `tests/test_analysis_context.py`

- [ ] **Step 1: Add failing table/column inference test**

Add a test named `test_sample_profile_inference_builds_table_and_column_profiles`.

The test should create catalog columns for `orders`:

```python
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
```

Expected assertions:

```python
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
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_sample_profile_inference_builds_table_and_column_profiles -q
```

Expected: fail with `NameError` or import error for `ProfileInferenceEngine`.

- [ ] **Step 3: Implement minimal inference engine**

Create `src/data_agent_backend/services/profile_inference.py` with:

```python
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
        table_type = self._table_type(table_name, column_profiles)
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
                                metadata=self._metadata(sample_limit, profiled_at, {"join_condition": "inferred"}, ["matched id column pattern"]),
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
        if name == "id" or name.endswith("_id") and name.startswith(column.table_name.lower().rstrip("s")):
            return "identifier"
        if name.endswith("_id"):
            return "foreign_key"
        if "timestamp" in data_type or "datetime" in data_type:
            return "datetime"
        if "date" in data_type:
            return "date"
        if "timestamp" in name or "datetime" in name:
            return "datetime_string" if self._looks_datetime(sample_values) else "datetime_string"
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

    def _looks_datetime(self, values: list[str]) -> bool:
        return any("-" in value and ":" in value for value in values)

    def _primary_date_column(self, profiles: list[ColumnProfile]) -> str | None:
        preferred = ("created", "updated", "purchase", "order", "event")
        date_profiles = [profile for profile in profiles if profile.semantic_type in {"datetime", "date", "datetime_string", "date_string"}]
        for token in preferred:
            for profile in date_profiles:
                if token in profile.column_name.lower():
                    return profile.column_name
        return date_profiles[0].column_name if date_profiles else None

    def _table_type(self, table_name: str, profiles: list[ColumnProfile]) -> str:
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
                metadata=self._metadata(sample_limit, profiled_at, {"table_name": "inferred"}, [f"promoted {table_type} table"]),
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
```

- [ ] **Step 4: Run the unit test**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_sample_profile_inference_builds_table_and_column_profiles -q
```

Expected: pass.

### Task 2: Join and Mart Candidate Tests

**Files:**
- Modify: `tests/test_analysis_context.py`
- Modify: `src/data_agent_backend/services/profile_inference.py`

- [ ] **Step 1: Add failing join/mart inference test**

Add `test_sample_profile_inference_builds_join_and_mart_candidates`.

Use catalog for `customers`, `orders`, and `mart_order_summary`. Include `customers.customer_id`, `orders.customer_id`, and `mart_order_summary.order_date`.

Expected assertions:

```python
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
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_sample_profile_inference_builds_join_and_mart_candidates -q
```

Expected: fail until join ordering and mart inference are correct.

- [ ] **Step 3: Adjust implementation**

Make `infer_join_paths()` produce deterministic table order and relation strings. For same-name `_id` columns, format the condition as:

```python
join_condition=f"{left_table}.{left.column_name} = {right_table}.{right.column_name}"
```

where `left_table` and `right_table` are sorted alphabetically by table name.

- [ ] **Step 4: Run the two inference tests**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_sample_profile_inference_builds_table_and_column_profiles tests/test_analysis_context.py::test_sample_profile_inference_builds_join_and_mart_candidates -q
```

Expected: both pass.

### Task 3: Manual Field Override Preservation

**Files:**
- Modify: `src/data_agent_backend/services/analysis_profile_store.py`
- Modify: `src/data_agent_backend/services/semantic_registry.py`
- Modify: `tests/test_analysis_context.py`

- [ ] **Step 1: Add failing table/column override test**

Add `test_inferred_profile_upsert_preserves_manual_field_sources`.

Setup:

```python
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
```

Then upsert an inferred profile for the same table:

```python
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
```

Expected:

```python
stored = services.analysis_profile_store.get_table_profile(datasource_id, "orders")
assert stored.primary_date_column == "paid_at"
assert stored.row_count == 200
assert stored.metadata["field_sources"]["primary_date_column"] == "manual"
assert stored.metadata["field_sources"]["row_count"] == "catalog"
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_inferred_profile_upsert_preserves_manual_field_sources -q
```

Expected: fail because the current upsert overwrites the whole row.

- [ ] **Step 3: Implement field merge helpers**

In `AnalysisProfileStore`, add private helpers:

```python
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
```

Before writing table profile, fetch existing profile and preserve any field where existing metadata marks that field as manual:

```python
if existing is not None:
    metadata = self._merge_metadata(existing.metadata, profile.metadata)
    profile = profile.model_copy(
        update={
            "primary_date_column": existing.primary_date_column
            if self._is_manual(existing.metadata, "primary_date_column")
            else profile.primary_date_column,
            "table_type": existing.table_type if self._is_manual(existing.metadata, "table_type") else profile.table_type,
            "description": existing.description if self._is_manual(existing.metadata, "description") else profile.description,
            "metadata": metadata,
        }
    )
```

Apply equivalent logic for `ColumnProfile` fields: `semantic_type`, `description`, `sample_values`, `null_ratio`, `distinct_count`.

- [ ] **Step 4: Add semantic registry manual protection test**

Add `test_inferred_semantic_upsert_preserves_manual_join_and_mart_records`.

Expected:

```python
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
    manual.model_copy(update={"join_condition": "orders.customer_id = customers.customer_id", "confidence": 0.7, "metadata": {"field_sources": {"join_condition": "inferred", "confidence": "inferred"}}})
)
joins = services.semantic_registry.get_join_paths(datasource_id, ["orders", "customers"])
assert any(join.join_condition == "orders.customer_id = customers.customer_unique_id" and join.confidence == 0.95 for join in joins)
```

- [ ] **Step 5: Implement semantic protection**

Because `semantic_join_paths` primary key includes `join_condition`, do not overwrite manual rows. For inferred rows, insert normally. For `semantic_marts`, merge fields similarly to table profiles when existing metadata has manual field sources.

- [ ] **Step 6: Run override tests**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_inferred_profile_upsert_preserves_manual_field_sources tests/test_analysis_context.py::test_inferred_semantic_upsert_preserves_manual_join_and_mart_records -q
```

Expected: pass.

### Task 4: MySQL Connector Sample Profiling

**Files:**
- Modify: `src/data_agent_backend/services/connectors/mysql.py`
- Modify: `tests/test_analysis_context.py`

- [ ] **Step 1: Add connector contract test with fake connection behavior**

Add a test using a fake connector if direct SQLAlchemy mocking becomes too invasive. The test should assert that profiling output from connector-style sample rows includes:

```python
assert result.table_profiles[0].metadata["profile"]["strategy"] == "limit"
assert result.table_profiles[0].metadata["profile"]["sample_limit"] == 20
assert result.column_profiles[0].metadata["field_sources"]["sample_values"] == "sample"
```

- [ ] **Step 2: Update `MySQLConnector.profile_tables()`**

Change the method to:

- group catalog columns by table
- read row estimates from `information_schema.tables`
- sample up to 20 catalog columns per table
- run `SELECT quoted_columns FROM quoted_table LIMIT :sample_limit`
- pass sample rows to `ProfileInferenceEngine.infer_table()`
- return combined `DatasourceProfileResult`

Keep `_quote_identifier()` for table and column names. Do not use `ORDER BY RAND()`.

- [ ] **Step 3: Preserve existing error behavior**

If a table sample query fails, add fallback profiles inferred from catalog only and put this metadata on the table profile:

```python
metadata={
    "profile": {
        "strategy": "limit",
        "sample_limit": sample_limit,
        "source": "mysql_sample",
        "skipped_reason": str(exc),
    }
}
```

If every table fails due to connection or query errors, raise the existing `DATASOURCE_QUERY_ERROR`.

- [ ] **Step 4: Run related tests**

Run:

```powershell
uv run pytest tests/test_analysis_context.py tests/test_datasources.py -q
```

Expected: pass.

### Task 5: Persist Inferred Join Paths and Mart Candidates

**Files:**
- Modify: `src/data_agent_backend/services/datasource_service.py`
- Modify: `tests/test_analysis_context.py`

- [ ] **Step 1: Add failing service integration test**

Add `test_profile_datasource_persists_inferred_marts_and_join_paths`.

Use a `ProfilingConnector` returning `DatasourceProfileResult` with table profiles, column profiles, and place inferred semantic objects in `metadata` if the connector result model is not expanded. Prefer not to change `DatasourceProfileResult` unless needed.

Expected after `analysis_profile_datasource(...)`:

```python
marts = services.semantic_registry.list_marts(datasource_id)
joins = services.semantic_registry.get_join_paths(datasource_id, ["orders", "customers"])
assert [mart.table_name for mart in marts] == ["mart_order_summary"]
assert any("customer_id" in join.join_condition for join in joins)
```

- [ ] **Step 2: Decide result transport**

Use `DatasourceProfileResult.usage_notes` only for human notes, not structured candidates. Add optional fields to `DatasourceProfileResult`:

```python
join_paths: list[JoinPath] = []
marts: list[MartDefinition] = []
```

Update imports in `models/analysis_context.py` carefully to avoid circular imports. `JoinPath` and `MartDefinition` already live in the same file, so this is safe.

- [ ] **Step 3: Persist semantic candidates**

In `DatasourceService.profile_datasource()` after storing table and column profiles:

```python
for mart in result.marts:
    self.semantic_registry.upsert_mart(mart)
for join_path in result.join_paths:
    self.semantic_registry.upsert_join_path(join_path)
```

Inject `semantic_registry` into `DatasourceService.__init__` and update `factory.py`.

- [ ] **Step 4: Run integration test**

Run:

```powershell
uv run pytest tests/test_analysis_context.py::test_profile_datasource_persists_inferred_marts_and_join_paths -q
```

Expected: pass.

### Task 6: API and MCP Regression Coverage

**Files:**
- Modify: `tests/test_analysis_context.py`
- Modify: `src/data_agent_backend/api/routes_analysis_context.py` only if payload defaults need adjustment
- Modify: `src/data_agent_backend/mcp/tools_analysis_context.py` only if signatures need adjustment

- [ ] **Step 1: Add API regression assertion**

Extend the existing HTTP profile test so `POST /analysis-context/{datasource_id}/profile` with `{}` uses default sample limit 20 and returns metadata:

```python
profiled = client.post(f"/analysis-context/{datasource_id}/profile", json={}).json()
assert profiled["ok"] is True
assert profiled["data"]["table_profiles"][0]["metadata"]["profile"]["sample_limit"] == 20
```

- [ ] **Step 2: Add MCP regression assertion**

Extend `test_analysis_context_mcp_tools_return_tool_result_envelope`:

```python
profiled = analysis_profile_datasource(datasource_id, services=services)
assert profiled.ok is True
assert profiled.data["table_profiles"][0]["metadata"]["profile"]["strategy"] == "limit"
```

- [ ] **Step 3: Run API/MCP tests**

Run:

```powershell
uv run pytest tests/test_analysis_context.py -q
```

Expected: pass.

### Task 7: Full Verification

**Files:**
- All changed implementation and test files

- [ ] **Step 1: Run full test suite**

Run:

```powershell
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Inspect diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected: changes are limited to profile inference implementation, datasource profiling integration, tests, and these docs.

- [ ] **Step 3: Do not commit unrelated user changes**

If committing later, stage only files touched for this feature. Leave existing unrelated changes such as `AGENTS.md` and `Backend.code-workspace` untouched unless the user explicitly asks to include them.

Suggested commit message:

```text
Add sample-based profile inference
```

## Self-Review

- Spec coverage: table profile, column profile, join candidate, mart candidate, freshness metadata, no LLM, sample-only mode, and manual override behavior are each mapped to tasks.
- Placeholder scan: no task depends on undefined future work.
- Type consistency: new inference result types use existing `TableProfile`, `ColumnProfile`, `JoinPath`, and `MartDefinition` models.
- Scope check: connector expansion, exact statistics, random sampling, and UI are intentionally excluded.

