# Sample Profile Inference Design

## Goal

`data_agent_backend`가 DB catalog와 제한된 row sample을 기반으로 분석용 metadata 초안을 자동 생성하고, 사용자가 보정한 metadata는 field 단위로 보호한다.

## Decisions

- Backend 방향은 ORM 중심이 아니라 DB introspection, lightweight profiling, semantic registry 구조를 유지한다.
- LLM은 metadata 생성에 개입하지 않는다.
- Catalog는 전체 schema를 introspection한다.
- Data profile은 단순 sample 기반으로 한다.
- 기본 sample 전략은 `LIMIT 20`이며 `ORDER BY RAND()`와 full scan aggregate는 사용하지 않는다.
- 자동 추론값과 수동 보정값은 기존 `metadata_json`에 provenance를 기록한다.
- 충돌 시 수동 보정값이 field 단위로 우선한다.

## Scope

포함 범위:

- Table profile 자동 초안 생성
- Column profile 자동 초안 생성
- Join path 후보 자동 생성
- Mart 후보 자동 생성
- Profile freshness/provenance metadata 기록
- Manual field override 보호
- HTTP API와 MCP tool의 기존 envelope 유지
- pytest 기반 회귀 테스트

제외 범위:

- LLM 기반 semantic enrichment
- 정확 통계용 full table scan
- `COUNT(DISTINCT)`, `null_ratio` 정확 계산
- random sampling
- 신규 datasource connector
- UI
- SQLite migration 추가. 1차는 기존 `metadata_json`을 사용한다.

## Architecture

현재 `DatasourceService.profile_datasource()`는 connector가 profile을 생성하면 `AnalysisProfileStore`에 저장한다. 이 고도화에서는 profile 생성 책임을 작은 rule-based inference 컴포넌트로 분리하고, MySQL connector는 catalog와 row sample 수집에 집중한다.

```text
refresh_catalog()
  -> connector.introspect()
  -> datasource_catalog_columns

profile_datasource(sample_limit=20)
  -> connector.profile_tables()
       -> information_schema table row estimate
       -> SELECT limited columns FROM table LIMIT 20
       -> ProfileInferenceEngine
  -> AnalysisProfileStore.upsert_* preserving manual fields
  -> SemanticRegistry.upsert inferred join/mart candidates
```

## Components

- `services/profile_inference.py`
  - 순수 Python rule-based inference 모듈이다.
  - catalog columns와 sampled rows를 받아 table profile, column profile, join path 후보, mart 후보를 만든다.
  - DB 접근을 하지 않는다.

- `services/connectors/mysql.py`
  - `profile_tables()`에서 sample limit 기본값을 적용한다.
  - table당 최대 sample column 수를 제한한다.
  - sample metadata를 inference engine에 전달한다.

- `services/analysis_profile_store.py`
  - 자동 upsert 시 기존 manual field를 덮어쓰지 않는다.
  - `metadata.field_sources`를 기준으로 field source를 판단한다.

- `services/semantic_registry.py`
  - inferred mart/join candidate를 저장할 때 manual record를 보호한다.
  - 동일 key 충돌 시 manual field source가 있는 값은 유지한다.

- `models/analysis_context.py`
  - 기존 모델을 유지한다.
  - 필요 시 metadata JSON에 `profile`, `field_sources`, `inference` key를 담는다.

## Metadata Contract

`metadata_json`은 다음 구조를 사용한다.

```json
{
  "field_sources": {
    "table_type": "inferred",
    "primary_date_column": "manual",
    "semantic_type": "inferred",
    "sample_values": "sample"
  },
  "profile": {
    "strategy": "limit",
    "sample_limit": 20,
    "sampled_columns_limit": 20,
    "profiled_at": "2026-05-19T00:00:00Z",
    "source": "mysql_sample"
  },
  "inference": {
    "version": 1,
    "confidence": 0.75,
    "reasons": ["matched *_id column pattern"]
  }
}
```

Allowed field source values:

- `manual`: user/API/seed supplied value. Auto refresh must preserve it.
- `inferred`: deterministic rule-based inference.
- `sample`: derived directly from limited sample rows.
- `catalog`: derived from DB catalog only.

## Inference Rules

Table profile:

- `primary_date_column`: first high-confidence date/datetime semantic column, preferring names containing `created`, `updated`, `purchase`, `order`, `event`.
- `table_type`: `mart` when table name starts with `mart_` or contains `_mart`; `dimension` when table name starts with `dim_` or has many identifier/name/code columns; otherwise `raw`.
- `row_count`: MySQL information_schema estimate only, with metadata marking it as estimated.

Column profile:

- `semantic_type`: determined from column name, DB type, and sample parseability.
- Supported first-pass types: `identifier`, `foreign_key`, `datetime`, `date`, `datetime_string`, `date_string`, `categorical`, `measure`, `boolean`, `text`.
- `sample_values`: up to 5 non-null distinct stringified values from the limited sample.
- `null_ratio` and `distinct_count`: left as `None` in sample mode because the sample is not a reliable statistic.

Join path candidates:

- Match columns with identical names ending in `_id`.
- Match table singular prefix plus `_id`, for example `customers.id` and `orders.customer_id`.
- Confidence starts at `0.65` and increases when data type matches, sample values overlap, or one side is named `id`.
- Candidates are stored as semantic join paths with metadata source `inferred`.

Mart candidates:

- Tables named `mart_*`, `*_mart`, `fact_*`, or `dim_*` are promoted to semantic mart candidates.
- Priority is highest for explicit `mart_*`, then `fact_*`, then `dim_*`.
- Date column is copied from inferred table profile when available.

## Error Handling

- Sampling failures for one table should not fail the whole datasource profile unless every table fails.
- Partial profile results include table-level `skipped_reason` in metadata.
- Invalid datasource ids continue to fail through existing registry/service behavior.
- Profile refresh must remain read-only.

## Testing

Tests must cover:

- Table and column inference from catalog plus sample rows.
- `sample_limit=20` default behavior.
- `null_ratio` and `distinct_count` remain `None` in sample mode.
- Join path candidates are inferred from `_id` patterns.
- Mart candidates are inferred from table names.
- Manual field sources are preserved on subsequent automatic profile refresh.
- HTTP/MCP wrappers keep returning `ToolResult`.
- Full test suite passes with `uv run pytest -q`.

