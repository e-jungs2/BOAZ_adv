# Context Pack v2 설계

## 목표

`build_analysis_context`가 Agent에게 단순 catalog 검색 결과만 넘기지 않고, SQL 작성 전에 바로 참고할 수 있는 구조화된 분석 패키지를 제공한다. 이번 범위는 Context Pack v2에 한정하며, datasource profile을 자동으로 생성하는 Profile Bootstrap은 후속 작업으로 분리한다.

## 배경

실행 로그에서 `build_analysis_context`가 빈 `catalog_matches`, `table_profiles`, `metrics`, `marts`, `join_paths`를 반환했고, Agent는 전체 catalog summary를 보고 SQL을 추측했다. 그 결과 MySQL datasource에 SQLite 함수인 `julianday`, `strftime`을 사용했고, 복구 가능한 오류 정보를 충분히 받지 못해 최종 분석을 완료하지 못했다.

이미 1차 보강으로 datasource별 `dialect_capabilities`와 `query_guidance`가 추가되었고, 한국어 질문의 기본 schema token 확장도 들어갔다. Context Pack v2는 이 기반 위에서 Agent가 사용할 추천 테이블, 컬럼, 조인, 시간 계산, 지표, 경고를 더 명시적으로 제공한다.

## 범위

포함한다.

- `AnalysisContext` 응답 모델에 Agent 친화 필드 추가
- 기존 catalog, semantic registry, 저장된 profile, dialect capabilities를 조합한 추천 생성
- profile 정보가 없을 때도 catalog 기반 partial context 반환
- profile 누락, join 후보 불확실성, grain 위험 같은 경고 제공
- 실행 로그 질문인 “배송은 빠르지만 리뷰는 낮은 주문의 특징은 뭐야?”를 회귀 테스트로 고정

포함하지 않는다.

- catalog refresh 이후 profile을 자동 생성하는 Profile Bootstrap
- 실제 DB에 추가 sampling query 실행
- Agent prompt 전면 개편
- SQL 자동 생성 또는 실행 계획 artifact 저장
- 새로운 datasource connector 추가

## 모델 변경

`src/data_agent_backend/models/analysis_context.py`에 다음 모델을 추가한다.

- `RecommendedTable`
  - `table_name`
  - `schema_name`
  - `reason`
  - `confidence`
  - `source`
  - `warnings`
- `RecommendedColumn`
  - `table_name`
  - `column_name`
  - `schema_name`
  - `data_type`
  - `semantic_type`
  - `role`
  - `reason`
  - `confidence`
- `JoinHint`
  - `left_table`
  - `right_table`
  - `join_condition`
  - `relationship_type`
  - `confidence`
  - `source`
  - `warnings`
- `TimeFilterHint`
  - `name`
  - `table_name`
  - `column_names`
  - `expression_hint`
  - `dialect`
  - `reason`
- `MetricHint`
  - `name`
  - `expression_hint`
  - `table_name`
  - `column_names`
  - `reason`
  - `source`
- `AnalysisWarning`
  - `code`
  - `message`
  - `severity`
  - `details`

`AnalysisContext`에 다음 필드를 추가한다.

- `recommended_tables: list[RecommendedTable]`
- `recommended_columns: list[RecommendedColumn]`
- `join_hints: list[JoinHint]`
- `time_filter_hints: list[TimeFilterHint]`
- `metric_hints: list[MetricHint]`
- `analysis_warnings: list[AnalysisWarning]`

기존 필드인 `catalog_matches`, `table_profiles`, `column_profiles`, `metrics`, `business_terms`, `marts`, `join_paths`, `dialect_capabilities`, `query_guidance`, `usage_notes`는 유지한다. 기존 API/MCP 소비자가 깨지지 않도록 새 필드는 기본값이 빈 list인 additive change로 둔다.

## 추천 생성 규칙

### Recommended Tables

`catalog_matches`를 기본 후보로 사용한다. semantic registry의 metric, business term, mart가 지목한 table은 catalog match에 없더라도 후보에 병합한다.

우선순위는 다음 순서로 계산한다.

1. semantic registry 또는 mart가 명시한 테이블
2. 질문 token과 table name이 직접 매칭된 테이블
3. 질문 token과 column name이 매칭된 테이블
4. 저장된 table profile이 있는 테이블

profile이 없는 경우에도 catalog 기반 추천은 반환하되, `analysis_warnings`에 `profile_missing`을 추가한다.

### Recommended Columns

`catalog_matches.columns`와 저장된 `column_profiles`를 병합한다. 컬럼 역할은 다음 규칙으로 분류한다.

- `metric`: `review_score`, `price`, `freight_value`, numeric measure, semantic metric expression에 포함된 컬럼
- `time`: 이름 또는 semantic type이 date, datetime, timestamp 계열인 컬럼
- `join_key`: `_id`로 끝나거나 join path에 포함된 컬럼
- `dimension`: category, status, type, city, state, seller, customer, product 계열 컬럼
- `identifier`: order_id, product_id, customer_id, seller_id 같은 식별자

실행 로그 질문에서는 최소한 다음 컬럼 계열이 추천되어야 한다.

- `orders.order_delivered_carrier_date`
- `orders.order_delivered_customer_date`
- `orders.order_estimated_delivery_date`
- `order_reviews.review_score`
- `order_items.price`
- `order_items.freight_value`

### Join Hints

저장된 `join_paths`가 있으면 그대로 `join_hints`로 변환한다. 저장된 join path가 없으면 이번 범위에서는 DB query를 실행하지 않고 catalog column name만 보고 약한 후보를 만든다.

catalog 기반 join 후보는 다음 조건에서만 만든다.

- 양쪽 테이블에 같은 `_id` 컬럼이 있다.
- 한쪽의 `id`와 다른 쪽의 `<table_singular>_id`가 대응한다.

catalog 기반 join 후보는 `source="catalog_inferred"`와 낮은 confidence를 사용하고, `warnings`에 “catalog 이름 기반 후보이며 실제 cardinality는 검증되지 않았다”는 메시지를 포함한다.

### Time Filter Hints

날짜/시간 컬럼 후보와 dialect capabilities를 조합한다. MySQL datasource에서는 `TIMESTAMPDIFF` 기반 예시를 사용한다.

실행 로그 질문의 “배송은 빠르지만”은 다음 의미로 해석한다.

- 배송 소요 시간 후보: `order_delivered_carrier_date`에서 `order_delivered_customer_date`까지의 차이
- 예상 대비 지연 후보: `order_estimated_delivery_date`와 `order_delivered_customer_date`의 차이

정확한 threshold는 Agent가 질문에 맞게 정하되, hint에는 계산식과 후보 컬럼을 제공한다.

### Metric Hints

semantic registry의 metric을 우선 사용한다. 없으면 catalog와 column role 기반으로 다음 계열을 만든다.

- 리뷰 품질: `review_score`
- 가격: `price`
- 운임: `freight_value`
- 주문 수: `COUNT(DISTINCT order_id)`

metric hint는 SQL 전체를 강제하지 않고 expression hint만 제공한다.

### Analysis Warnings

다음 상황에서 경고를 반환한다.

- `profile_missing`: matched table에 저장된 table/column profile이 없다.
- `join_unverified`: join hint가 catalog 이름 기반 추론이다.
- `grain_risk`: order-level 질문인데 item-level 테이블을 join해야 해서 row multiplication 위험이 있다.
- `dialect_guidance_missing`: datasource dialect capabilities를 가져올 수 없다.
- `context_partial`: 추천은 가능하지만 semantic/profile 정보가 충분하지 않다.

경고는 Agent가 최종 답변에서 한계사항으로 반영할 수 있도록 `code`, `message`, `severity`, `details`를 포함한다.

## 데이터 흐름

1. Agent가 `build_analysis_context(question)`를 호출한다.
2. `AnalysisContextService`가 datasource 존재 여부를 확인한다.
3. semantic registry에서 metric, business term, mart 후보를 조회한다.
4. catalog search로 질문과 관련된 table/column을 찾는다.
5. 저장된 table/column profile과 join path를 병합한다.
6. datasource service에서 dialect capabilities를 가져온다.
7. Context Pack v2 추천 필드를 생성한다.
8. 기존 context 필드와 새 추천 필드를 함께 반환한다.

## 오류 처리와 부분 성공

Context Pack v2는 profile이나 semantic 정보가 없어도 실패하지 않는다. datasource 자체가 없거나 policy에서 read가 차단되는 경우만 기존처럼 실패한다.

profile이나 join path가 없는 경우에는 빈 list 대신 catalog 기반 후보와 `analysis_warnings`를 반환한다. dialect capabilities를 가져올 수 없는 경우에도 context 생성은 계속하고 `dialect_guidance_missing` 경고를 추가한다.

## 테스트 전략

단위 테스트는 `tests/test_analysis_context.py`에 추가한다.

- 한국어 질문 “배송은 빠르지만 리뷰는 낮은 주문의 특징은 뭐야?”에서 `orders`, `order_reviews`, `order_items`가 `recommended_tables`에 포함된다.
- `review_score`, 배송 날짜 컬럼, `price`, `freight_value`가 `recommended_columns`에 포함된다.
- MySQL datasource에서 `time_filter_hints`에 `TIMESTAMPDIFF` 기반 expression hint가 포함된다.
- profile이 없는 경우 `profile_missing` 경고가 포함된다.
- 저장된 join path가 없더라도 `_id` 기반 catalog join hint가 생성되고 `join_unverified` 경고가 포함된다.

기존 테스트는 유지한다.

- `catalog_matches` 기존 동작
- MCP/HTTP `ToolResult` envelope
- dialect capabilities 기존 보강 테스트

## 완료 기준

- `AnalysisContext`가 기존 필드를 유지하면서 Context Pack v2 필드를 추가로 반환한다.
- 실행 로그 질문에서 Agent가 필요한 테이블, 컬럼, 시간 계산 힌트를 context에서 받을 수 있다.
- profile이 없는 상태에서도 context가 비지 않고 partial recommendation과 warning을 반환한다.
- 새 테스트와 기존 전체 테스트가 통과한다.
