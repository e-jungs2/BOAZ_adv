# Analysis Context MVP Design

## Goal

Agent가 질문을 받으면 Backend에서 관련 catalog, profile, semantic, mart, join 후보를 가져와 SQL을 만들 수 있게 한다.

## Scope

이번 MVP는 완성형 semantic layer나 vector search를 만들지 않는다. 대신 Agent가 SQL을 생성하기 전에 Backend에서 분석 맥락을 조회할 수 있는 안정적인 tool contract와 저장 구조를 만든다.

포함 범위:

- catalog keyword search
- table/column profile 저장 및 조회
- metric, business term, mart, join path registry
- 통합 analysis context 조회
- MCP/API tool 노출
- DeepAgent tool/prompt 확장

제외 범위:

- vector embedding search
- DB별 고급 optimizer
- 자동 semantic inference
- 자동 join graph inference
- Web UI

## Architecture

기존 datasource catalog는 table/column 목록의 source of truth로 유지한다. 새 Analysis Context 계층은 catalog 위에 profile과 semantic registry를 더하고, Agent가 질문 단위로 필요한 후보만 가져가도록 한다.

```text
User Question
  -> DeepAgent
  -> build_analysis_context(datasource_id, question)
  -> AnalysisContextService
       -> DatasourceRegistry catalog
       -> AnalysisProfileStore
       -> SemanticRegistry
  -> SQL generation
  -> datasource_query
```

## Components

- `models/analysis_context.py`: catalog match, profile, metric, business term, mart, join path, 통합 context 모델
- `services/analysis_context_service.py`: search와 context 조립 로직
- `services/analysis_profile_store.py`: table/column profile SQLite 저장소
- `services/semantic_registry.py`: metric/business term/mart/join path SQLite 저장소
- `mcp/tools_analysis_context.py`: MCP tool contract
- `api/routes_analysis_context.py`: HTTP API wrapper

## Data Model

Profile:

- `table_profiles`: datasource, schema, table, row_count, table_type, description, primary_date_column, metadata
- `column_profiles`: datasource, schema, table, column, semantic_type, description, null_ratio, distinct_count, sample_values, metadata

Semantic registry:

- `semantic_metrics`: metric name, description, expression, recommended table, filters, dimensions
- `semantic_terms`: business term, description, related tables, related columns, related metrics
- `semantic_marts`: mart table, description, grain, date column, priority, related metrics
- `semantic_join_paths`: left table, right table, join condition, relationship type, confidence

## Tool Contract

- `analysis_catalog_search(datasource_id, query, limit=10)`
- `analysis_get_table_profile(datasource_id, table_name, schema_name=None)`
- `analysis_get_column_profile(datasource_id, table_name, column_name, schema_name=None)`
- `analysis_semantic_search(datasource_id, query, limit=10)`
- `analysis_get_join_paths(datasource_id, table_names)`
- `analysis_build_context(datasource_id, question, limit=10)`

All tools return the existing `ToolResult` envelope.

## Error Handling

Unknown datasource ids are rejected through the datasource service/registry. Missing profiles or semantic records return empty result sets rather than failing. Invalid registry payloads fail with `VALIDATION_ERROR`.

## Testing

Tests must cover:

- catalog search matches table and column names
- profile upsert/get behavior
- semantic registry upsert/search behavior
- build context combines catalog, profile, semantic, and join candidates
- MCP/API wrappers preserve `ToolResult`
- Agent layer exposes analysis context tools

