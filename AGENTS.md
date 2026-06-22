# AGENTS.md

## 언어 및 커뮤니케이션

- 사용자에게 답변하거나 작업 관련 문서를 작성할 때는 한국어로 진행한다.
- 코드 식별자, 파일명, 명령어, API 이름은 원문 그대로 쓴다.
- 구현 전후 설명은 간결하게 하되, 범위와 검증 결과는 명확히 남긴다.

## 최종 목표

최종 목표는 `data_agent_backend`를 **데이터 분석 전용 Agent Product의 Backend Core + Agent Orchestration 기반**으로 발전시키는 것이다.

이 제품의 주도권은 LangChain/LangGraph 기반 Agent와 LLM이 가진다. Backend는 Agent가 좋은 분석을 수행할 수 있도록 datasource 연결, SQL 실행, Python 실행, artifact 저장, run 기록, policy 검증을 제공하는 **안전한 실행/저장/검증 계층**이어야 한다.

Backend가 분석 의사결정을 직접 수행하지 않는다.

Backend가 하지 않는 것:

- 분석 계획 수립
- 어떤 SQL을 작성할지 결정
- 결과 해석
- 다음 분석 방향 판단
- LLM reasoning 대체
- Agent state graph 역할 수행

Backend가 책임지는 것:

- datasource metadata 등록/조회
- per-request credential 기반 외부 DB 연결
- schema/table/sample 조회
- read-only SQL 검증 및 실행
- Python sandbox 실행
- artifact 저장 및 lineage 관리
- run/event 기록
- policy 평가
- Agent tool이 호출할 안정적인 service interface 제공

## 최종 목표 폴더 구조

최종적으로 지향하는 구조는 다음과 같다.

```text
data_agent_backend/
  api/
    app.py
    deps.py
    common.py

    routes_datasources.py
    routes_execution.py
    routes_runs.py
    routes_artifacts.py
    routes_policy.py
    routes_agent.py

    routes_memory.py        # optional
    routes_approvals.py     # optional
    routes_workspace.py     # optional
    routes_exports.py       # optional
    routes_catalog.py       # optional

  agent/
    graph.py                # LangGraph state graph
    state.py                # Agent state 정의
    nodes.py                # planning/analyze/reflect/report node
    tools.py                # Backend service를 감싸는 LangChain Tool
    prompts.py              # prompt template
    llm.py                  # GPT/Claude provider wrapper
    runtime.py              # Agent 실행 entrypoint

  models/
    datasource.py
    execution.py
    artifacts.py
    runs.py
    policy.py
    contexts.py
    tool_results.py
    common.py

    agent.py                # Agent request/response/state schema
    memory.py               # optional
    approvals.py            # optional
    workspace.py            # optional

  services/
    factory.py

    datasource_service.py
    sql_executor.py
    sandbox_executor.py
    artifact_registry.py
    artifact_store.py
    run_service.py
    policy_engine.py

    connectors/
      base.py
      registry.py
      mysql_connector.py
      postgres_connector.py
      sqlite_connector.py

    memory_store.py         # optional
    approval_store.py       # optional
    workspace_backend.py    # optional
    workspace_router.py     # optional
    workspace_storage_service.py
    export_service.py       # optional
    catalog_store.py        # optional
    checkpoint_manager.py   # optional 또는 LangGraph 연동 전 재검토

  storage/
    sqlite.py
    migrations.py
    filesystem.py

  tests/
    test_api_core_routes.py
    test_datasource_api.py
    test_datasource_introspection.py
    test_connector_registry.py
    test_sql_executor_datasource.py
    test_agent_tools.py
    test_agent_graph.py
```

## 현재 단계 목표

현재 단계는 최종 Agent 구조를 바로 구현하지 않는다.

현재 단계의 목표는 Agent가 나중에 안정적으로 사용할 수 있는 **Backend Core 실행 계층**을 먼저 정리하는 것이다.

현재 기본 Backend 앱은 Core 기능만 조립하고 노출한다.

Core 기능:

- `DatasourceService`
- `ConnectorRegistry`
- `SQLExecutor`
- `SandboxExecutor`
- `ArtifactRegistry`
- `ArtifactStore`
- `RunService`
- `PolicyEngine`
- 내부 `SQLiteStore`

기본 API 앱에서 노출하는 endpoint:

- `GET /health`
- `/datasources`
- `/execution`
- `/runs`
- `/artifacts`
- `/policy`

Optional 기능은 삭제하지 않고 보존하되, 기본 조립 경로에서는 제외한다.

Optional 기능:

- `MemoryStore`
- `ApprovalStore`
- `WorkspaceBackend`
- `WorkspaceRouter`
- `WorkspaceStorageService`
- `ExportService`
- `CatalogStore`
- `CheckpointManager`

Optional API 라우터:

- `/memory`
- `/approvals`
- `/workspace`
- `/exports`
- `/catalog`

Optional 기능을 다시 활성화할 때는 암묵적으로 기본 앱에 섞지 말고, `create_full_services()` 또는 `create_app(include_optional=True)` 같은 명시적 경로를 도입한다.

## Agent 연동 원칙

나중에 `agent/`를 추가하더라도 Agent는 외부 DB나 내부 저장소에 직접 접근하지 않는다.

Agent tool은 Backend service를 감싸는 얇은 wrapper여야 한다.

```text
LangChain/LangGraph Agent
  -> agent/tools.py
  -> SQLExecutor
  -> DatasourceService
  -> ConnectorRegistry
  -> External DB Connector
  -> 사용자 분석 DB
```

Python 실행도 같은 원칙을 따른다.

```text
Agent Python Tool
  -> SandboxExecutor
  -> ArtifactRegistry
  -> RunService
```

Memory도 직접 DB를 만지지 않는다.

```text
Agent Memory Tool
  -> MemoryStore
  -> Internal SQLiteStore
```

## Datasource 정책

- datasource metadata에는 password를 저장하지 않는다.
- password 또는 credential은 연결 테스트, schema 조회, sample 조회, SQL 실행 요청 시점에만 받는다.
- credential은 응답, artifact metadata, 내부 SQLite에 저장하거나 노출하지 않는다.
- datasource 목록/조회 응답에는 기본적으로 host, username, password 같은 민감 연결 정보를 노출하지 않는다.
- `datasource_id`가 명시되면 해당 datasource를 사용한다.
- `datasource_id`가 필요한 API에서 누락되면 임의 datasource를 선택하지 않는다.
- datasource가 없거나 모호한 경우 조용히 fallback하지 말고 명확한 오류를 반환한다.

## Connector 정책

외부 분석 DB connector는 단일 MySQL 구현에 고정하지 않는다.

권장 구조:

```text
data_agent_backend/services/connectors/
  base.py
  registry.py
  mysql_connector.py
  postgres_connector.py
  sqlite_connector.py
```

각 connector는 공통 인터페이스를 따른다.

- `test_connection`
- `fetch_catalog`
- `describe_table`
- `sample_rows`
- `execute_query`
- `rows_to_csv`

DatasourceService는 특정 connector를 직접 import해서 생성하지 않고 registry를 통해 datasource type에 맞는 connector를 생성한다.

외부 분석용 SQLite connector는 내부 저장소인 `data_agent_backend/storage/sqlite.py`와 역할이 다르다. 이름과 책임을 명확히 분리한다.

## SQL 실행 정책

- SQL 실행은 Backend의 `SQLExecutor`를 통해서만 수행한다.
- SQL 실행 전 read-only 검증을 수행한다.
- `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE` 등 쓰기/DDL 계열 SQL은 차단한다.
- multi-statement SQL은 차단한다.
- `row_limit`은 명시적으로 검증한다. `0` 또는 음수 값을 조용히 기본값으로 대체하지 않는다.
- SQL 실행 결과는 기존 artifact 중심 흐름을 유지한다.
- SQL 실행 실패 시 legacy tool이나 다른 connector로 우회하지 않는다.

## 하드코딩 및 fallback 금지

금지 항목:

- DB host, port, database, username, password 하드코딩
- datasource id 하드코딩
- table 이름, column 이름, sample query 하드코딩
- connector 실패 시 다른 connector나 legacy SQL 도구로 조용히 우회
- datasource가 없거나 모호할 때 임의 datasource 선택
- production 경로에서 mock data, demo data, fake schema 사용
- 설정 누락 시 자동 대체값으로 조용히 진행
- password 누락 시 빈 문자열로 연결 시도
- 오류 방지를 이유로 default datasource 자동 등록
- 환경변수 기반 datasource 자동 등록을 production 기본 경로에 추가

테스트 fixture 안의 가짜 DB 정보는 허용하되 production 경로와 명확히 분리한다.

## MCP 정책

MCP는 새 목표의 중심이 아니다.

- 신규 설계와 구현은 API/service 중심으로 진행한다.
- 기존 MCP 코드는 당장 전체 삭제하기보다, API/service 경계가 안정된 뒤 제거하거나 deprecated 처리한다.
- 새 기능을 MCP 전용으로 설계하지 않는다.
- 기존 `mcp/tools_*`에 있는 유용한 흐름은 service/API 계층으로 이동하거나 재사용한다.
- MCP profile 검증은 새 목표와 맞지 않으면 테스트에서 제거 또는 deprecated 처리한다.

## 작업 방식

- 제품 코드 수정 전에 관련 테스트를 먼저 작성한다.
- 각 변경은 실패 테스트 작성, 실패 확인, 최소 구현, 통과 확인 순서로 진행한다.
- 기존 사용자 변경을 임의로 되돌리지 않는다.
- 설계와 충돌하는 요구가 발견되면 임의로 우회하지 말고 AGENTS.md 또는 관련 계획 문서를 먼저 갱신한다.
- `.superpowers/`는 brainstorming visual companion 산출물이므로 기본 커밋 범위에 포함하지 않는다.

## 파일 경계

유지 우선:

- `data_agent_backend/services/datasource_service.py`
- `data_agent_backend/services/sql_executor.py`
- `data_agent_backend/services/artifact_registry.py`
- `data_agent_backend/services/run_service.py`
- `data_agent_backend/services/policy_engine.py`
- `data_agent_backend/services/sandbox_executor.py`
- `data_agent_backend/storage/sqlite.py`
- `data_agent_backend/services/connectors/`

Core 조립 경로:

- `data_agent_backend/services/factory.py`
- `data_agent_backend/api/app.py`

Optional 보존 대상:

- `data_agent_backend/services/memory_store.py`
- `data_agent_backend/services/approval_store.py`
- `data_agent_backend/services/workspace_backend.py`
- `data_agent_backend/services/workspace_router.py`
- `data_agent_backend/services/workspace_storage_service.py`
- `data_agent_backend/services/export_service.py`
- `data_agent_backend/services/catalog_store.py`
- `data_agent_backend/services/checkpoint_manager.py`
- `data_agent_backend/api/routes_memory.py`
- `data_agent_backend/api/routes_approvals.py`
- `data_agent_backend/api/routes_workspace.py`
- `data_agent_backend/api/routes_exports.py`
- `data_agent_backend/api/routes_catalog.py`

주의:

- `data_agent_backend/storage/migrations.py`는 내부 SQLite schema 변경이 필요한 경우에만 수정한다.
- `data_agent_backend/services/sandbox_executor.py`는 datasource/Core 정리 범위에서 불필요하게 수정하지 않는다.
- Optional 코드는 삭제하지 말고 기본 앱 조립 경로에서만 제외한다.

## 검증 명령

기본 테스트:

```powershell
python -m pytest
```

가상환경을 명시해야 하는 경우:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

현재 로컬 환경에서 `python`이 Windows Store stub으로 동작하면 `.venv` Python을 사용한다.

주요 검증 포인트:

- 기본 `create_app()`은 Core endpoint만 노출한다.
- optional endpoint는 기본 앱에서 노출되지 않는다.
- `create_core_services()`는 optional service를 생성하지 않는다.
- datasource response에 password가 포함되지 않는다.
- datasource metadata 저장 경로에 password가 저장되지 않는다.
- credential 누락 시 실행 전에 명확한 오류가 발생한다.
- 외부 SQLite datasource와 내부 SQLiteStore가 혼동되지 않는다.
- MySQL/PostgreSQL/SQLite connector 선택이 registry를 통해 이뤄진다.
- read-only SQL 검증이 connector 실행 전에 적용된다.
- `row_limit <= 0`은 기본값으로 대체되지 않는다.
- connector 실패 시 다른 connector나 legacy 경로로 fallback하지 않는다.

## Git 주의사항

- 사용자가 만든 변경을 임의로 되돌리지 않는다.
- 관련 없는 변경은 커밋에 포함하지 않는다.
- 현재 작업과 무관한 삭제, 비추적 파일, generated 파일은 먼저 사용자 의도를 확인하거나 그대로 둔다.
