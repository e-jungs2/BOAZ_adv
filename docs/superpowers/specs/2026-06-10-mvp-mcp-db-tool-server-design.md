# MVP MCP DB Tool Server Design

## 목적

현재 백엔드는 에이전트에게 DB 컨텍스트를 한 번에 만들어 넘기는 서버가 아니라, MCP 표준을 따르는 DB 분석 도구 서버로 발전한다. 사용자는 `.env` 또는 환경변수에 분석 대상 DB 정보를 넣고 백엔드를 실행한다. 에이전트는 MCP에 노출된 제한된 DB 분석 도구를 사용해 스키마 탐색, 테이블 상세 확인, 샘플 조회, 분석 SQL 실행을 반복한다.

이번 MVP의 목표는 외부 에이전트가 처음 연결했을 때 DB 분석에 필요한 도구만 보고, 안전한 범위 안에서 적극적으로 SQL 분석을 수행할 수 있게 만드는 것이다.

## 범위

포함 범위:

- env 기반 datasource 자동 등록
- 기본 MCP 프로파일 `db_analysis`
- 에이전트에게 노출되는 DB 분석 도구 5개
- 분석용 SELECT SQL 실행
- Artifact 중심 표준 결과 envelope
- 기존 내부 SQLite schema 유지
- SQL 실행 전 내부 안전 검증
- 하드코딩과 숨은 fallback 금지

제외 범위:

- 서비스 내부 DB 재설계
- 내부 SQLite migration 추가
- query execution 전용 로그 테이블
- Python sandbox 고도화
- Agent SDK, Codex SDK, LangGraph 등 에이전트 orchestration 구현
- `db_validate_analysis_query`, `db_explain_analysis_query`
- PostgreSQL, SQLite 등 멀티 DB 커넥터 확장
- 비용 기반 쿼리 정책과 승인 흐름

## MCP 도구 노출 정책

기본 MCP 서버 프로파일은 `db_analysis`이다. 이 프로파일에서는 에이전트에게 아래 5개 도구만 노출한다.

- `db_list_datasources`
- `db_get_schema`
- `db_describe_table`
- `db_sample_rows`
- `db_run_analysis_query`

기존 MCP 도구 29개와 신규 DB 분석 도구 5개를 모두 포함하는 `full` 프로파일은 내부 개발과 디버깅용으로만 둔다. 기본 실행에서는 외부 에이전트가 `workspace_*`, `run_*`, `artifact_*`, `memory_*`, `approval_*`, `policy_*`, `catalog_*`, `sandbox_run_python`, 기존 `sql_run_query`, `export_create`를 볼 수 없어야 한다.

알 수 없는 MCP profile 값은 fail-fast 오류로 처리한다. 임의로 `db_analysis` 또는 `full`로 대체하지 않는다.

## Datasource 정책

DB 연결 정보는 env 또는 `.env`를 통해서만 입력한다. 백엔드는 시작 시 env를 읽어 datasource를 자동 등록한다. 에이전트는 datasource를 생성, 수정, 삭제할 수 없다.

MVP UX는 단일 기본 datasource를 기준으로 한다. 내부 모델과 도구 인자는 복수 datasource 확장을 고려해 `datasource_id`를 선택적으로 받을 수 있다.

Datasource 선택 규칙:

- `datasource_id`가 있으면 해당 datasource를 사용한다.
- `datasource_id`가 없고 등록된 datasource가 정확히 1개이면 그 datasource를 사용한다.
- 등록된 datasource가 0개이면 명확한 설정 오류를 반환한다.
- 등록된 datasource가 2개 이상이고 `datasource_id`가 없으면 임의 선택하지 않고 ambiguous 오류를 반환한다.

`db_list_datasources`는 에이전트에게 필요한 최소 식별 정보만 반환한다. host, username, password는 노출하지 않는다.

## 도구별 계약

모든 `db_*` 도구는 기존 `ToolResult` 형식을 유지한다. 성공 시 `{ "ok": true, "data": ... }`, 실패 시 `{ "ok": false, "error": ... }`를 반환한다.

### `db_list_datasources`

입력은 없다.

반환 데이터:

- `datasource_id`
- `name`
- `type`
- `database`
- `is_default`

민감 연결 정보는 반환하지 않는다.

### `db_get_schema`

입력:

- `datasource_id`: optional

반환 데이터:

- database 이름
- table 목록
- 각 table의 column 이름, 타입, nullable 여부, key 정보

전체 row count처럼 비용이 큰 정보는 MVP에서 포함하지 않는다.

### `db_describe_table`

입력:

- `table_name`: required
- `datasource_id`: optional

반환 데이터:

- table 이름
- column 상세
- key 정보
- nullable 여부

존재하지 않는 table이면 유사 이름을 추측하지 않고 명확한 오류를 반환한다.

### `db_sample_rows`

입력:

- `table_name`: required
- `datasource_id`: optional
- `limit`: optional

반환 데이터는 고정된 preview 구조를 사용한다.

- `columns`
- `rows`
- `truncated`
- `limit`

Table 이름은 문자열 연결이 아니라 connector의 안전한 identifier quoting 경로를 통해 처리한다.

### `db_run_analysis_query`

입력:

- `query`: required
- `datasource_id`: optional
- `row_limit`: optional

JOIN, CTE, aggregate, window function, subquery, UNION 등 분석용 SELECT SQL은 허용한다. DB 상태를 변경하는 DML, DDL, 프로시저 호출, 다중 statement는 차단한다.

SQL 실행 결과는 항상 Artifact 중심 표준 envelope로 반환한다.

```json
{
  "artifact_ref": {
    "artifact_id": "art_xxx",
    "type": "sql_result",
    "format": "csv"
  },
  "preview": {
    "columns": [],
    "rows": [],
    "truncated": true
  },
  "profile": {
    "returned_rows": 1000,
    "preview_rows": 50,
    "column_count": 12
  },
  "execution": {
    "datasource_id": "ds_xxx",
    "tool_name": "db_run_analysis_query",
    "row_limit": 1000,
    "runtime_ms": 120
  },
  "warnings": []
}
```

결과 크기에 따라 반환 방식은 바뀌지 않는다. 결과 데이터의 정본은 artifact이고, MCP 응답은 에이전트가 다음 판단을 할 수 있는 preview, profile, execution metadata, warnings를 같은 형식으로 제공한다.

## 안전성 및 오류 처리

MVP의 기본 보안 모델은 분석용 SELECT는 적극적으로 허용하되 DB 상태 변경은 금지하는 것이다. `db_run_analysis_query`는 실행 전에 내부 검증을 반드시 수행한다.

차단 대상:

- `INSERT`
- `UPDATE`
- `DELETE`
- `MERGE`
- `DROP`
- `ALTER`
- `CREATE`
- `TRUNCATE`
- `CALL`
- `LOAD`
- `COPY`
- 다중 statement
- 빈 쿼리

Row limit은 config에 정의된 기본값과 최대값을 따른다. MVP에서는 큰 row limit 요청을 승인 흐름으로 우회하지 않고 명확한 오류로 처리한다.

오류는 기존 `ToolResult.failure` 형식으로 반환한다.

```json
{
  "ok": false,
  "error": {
    "code": "SQL_VALIDATION_FAILED",
    "message": "Only analysis SELECT queries are allowed.",
    "details": {
      "blocked_keywords": ["DROP"]
    }
  }
}
```

## 하드코딩 및 fallback 금지

이번 구현에서는 하드코딩과 숨은 fallback을 금지한다. 이는 에이전트 도구 사용 흐름을 예측 가능하게 만들기 위한 제품 요구사항이다.

금지 항목:

- DB host, port, database, username, password 하드코딩
- datasource id 하드코딩
- table 이름, column 이름, sample query 하드코딩
- `db_*` 도구 실패 시 기존 `sql_run_query`로 우회
- datasource가 없거나 애매할 때 임의 datasource 선택
- production 경로에서 mock data, demo data, fake schema 사용
- 설정 누락 시 자동 대체값으로 조용히 진행

`datasource_id` 생략 시 env로 등록된 단일 datasource를 사용하는 것은 fallback이 아니라 명시된 기본 동작이다. 단, datasource가 0개이거나 2개 이상이면 오류를 반환한다.

Fallback이 필요한 경우는 테스트 fixture 또는 명시적 개발 모드에만 한정하고 production 코드 경로와 분리한다.

## 구현 구조

추가 파일:

- `data_agent_backend/mcp/tools_db.py`
- `data_agent_backend/models/db_tools.py`

수정 파일:

- `data_agent_backend/mcp/server.py`
- `data_agent_backend/services/datasource_service.py`
- `data_agent_backend/services/connectors/mysql_connector.py`
- `data_agent_backend/services/sql_executor.py`

테스트 추가:

- `data_agent_backend/tests/test_mcp_db_tools.py`
- `data_agent_backend/tests/test_datasource_introspection.py`

수정하지 않는 파일:

- `data_agent_backend/storage/migrations.py`
- `data_agent_backend/services/sandbox_executor.py`

### `mcp/tools_db.py`

에이전트에게 노출할 5개 DB 분석 도구를 정의한다.

- `db_list_datasources`
- `db_get_schema`
- `db_describe_table`
- `db_sample_rows`
- `db_run_analysis_query`

### `mcp/server.py`

도구 등록을 profile 기반으로 분리한다.

- `DB_ANALYSIS_TOOLS`: DB 분석 도구 5개만 포함
- `FULL_TOOLS`: 기존 도구 29개와 신규 DB 분석 도구 5개 포함
- `create_mcp_server(profile: str | None = None)`
- `DATA_AGENT_MCP_PROFILE` env 기본값은 `db_analysis`
- 알 수 없는 profile은 fail-fast

### `DatasourceService`

DB 탐색에 필요한 service method를 추가한다.

- `resolve_datasource_id(datasource_id: str | None) -> str`
- `list_agent_datasources()`
- `get_schema(datasource_id: str | None)`
- `describe_table(datasource_id: str | None, table_name: str)`
- `sample_rows(datasource_id: str | None, table_name: str, limit: int | None)`

### `MySQLConnector`

MySQL 전용 introspection과 안전한 identifier 처리를 맡는다.

- `describe_table(table_name: str)`
- `sample_rows(table_name: str, limit: int)`
- `quote_identifier(name: str)`
- `table_exists(table_name: str)`

기존 `fetch_catalog()`는 재사용하거나 필요한 범위에서 개선한다.

### `SQLExecutor`

기존 `run_sql_query`는 호환용으로 유지한다. 새 제품 표면에서는 `run_analysis_query`를 추가해 `db_run_analysis_query`가 사용한다.

`run_analysis_query` 책임:

- datasource resolve
- SQL validation
- policy evaluate
- query artifact 저장
- result artifact 저장
- Artifact 중심 envelope 반환

## 테스트 및 완료 기준

자동 테스트:

- 기본 `db_analysis` profile이 정확히 5개 도구만 등록하는지 검증
- `full` profile이 기존 도구와 신규 DB 도구를 모두 등록하는지 검증
- 알 수 없는 profile은 fail-fast인지 검증
- datasource가 없으면 명확한 오류 반환
- datasource가 2개 이상이고 `datasource_id`가 없으면 ambiguous 오류 반환
- `db_list_datasources`가 민감 정보를 반환하지 않는지 검증
- schema, table, sample 도구가 connector method를 통해 동작하는지 검증
- table 이름이 안전한 quoting 경로를 거치는지 검증
- `db_run_analysis_query`가 분석용 SELECT는 허용하고 DDL, DML, 다중 statement는 차단하는지 검증
- SQL 실행 결과가 항상 Artifact 중심 envelope를 반환하는지 검증
- 내부 SQLite migration이 추가되지 않았는지 확인
- 기존 `sql_run_query`가 기본 `db_analysis` profile에 노출되지 않는지 검증

수동 확인:

```powershell
$env:MYSQL_HOST="..."
$env:MYSQL_DATABASE="..."
$env:MYSQL_USERNAME="..."
$env:MYSQL_PASSWORD="..."
python -m data_agent_backend.mcp.server
```

MCP 클라이언트가 기본 실행에서 볼 수 있는 도구는 5개여야 한다. 에이전트는 아래 순서로 기본 분석 루프를 수행할 수 있어야 한다.

1. `db_list_datasources`
2. `db_get_schema`
3. `db_describe_table` 또는 `db_sample_rows`
4. `db_run_analysis_query`

## 후속 고도화

후속 단계에서 다룰 항목:

- 서비스 내부 DB 모델 재설계
- query execution 전용 로그 테이블
- Python sandbox 분석 실행 환경 고도화
- Agent SDK, Codex SDK, LangGraph orchestration 레이어
- `db_validate_analysis_query`
- `db_explain_analysis_query`
- PostgreSQL, SQLite 등 멀티 커넥터
- 비용 기반 쿼리 정책
- 승인 흐름
- read replica 권장 설정
