# Agent Runtime API Prototype Design

## Goal

데이터분석 전용 Backend와 Agent Layer를 하나의 프로토타입 제품 흐름으로 연결한다. 1차 목표는 기존 CLI 실행을 유지하면서, 같은 Agent 실행 엔진을 HTTP API에서도 호출할 수 있게 만드는 것이다.

프로토타입은 사용자의 자연어 질문을 받아 datasource 준비, catalog/profile/context 조회, read-only SQL 실행, run/artifact 기록, 최종 답변 생성을 하나의 실행 경로로 제공한다.

## Decisions

- 공통 실행 계층은 `data_agent_agent` 패키지에 둔다.
- CLI와 HTTP API는 같은 Agent Runtime을 호출하는 얇은 어댑터로 유지한다.
- Agent는 Backend 내부 서비스 클래스를 직접 import하지 않는다.
- Agent와 Backend의 논리적 경계는 기존 MCP tool contract와 `ToolResult` envelope로 유지한다.
- CLI 실행은 기존처럼 MCP stdio client를 통해 `data-agent-mcp` 서버와 연결한다.
- HTTP API 실행은 같은 프로세스의 `BackendServices`를 주입한 in-process backend tool adapter를 사용한다.
- 1차 HTTP API는 동기 요청/응답 방식의 `POST /agent/ask`만 제공한다.
- 실제 OpenAI 호출은 단위 테스트에서 수행하지 않고 fake agent/fake tool provider로 검증한다.

## Scope

포함 범위:

- 공통 `AgentRuntime` 또는 동등한 runtime service 추가
- CLI가 공통 runtime을 호출하도록 정리
- HTTP `POST /agent/ask` 추가
- MCP stdio 기반 tool provider 유지
- in-process backend tool provider 추가
- datasource 자동 준비 흐름 공유
- run 생성과 실행 metadata 기록 공유
- Agent 답변, run id, datasource id를 포함한 응답 모델 추가
- fake runtime/provider 기반 테스트

제외 범위:

- 비동기 background run API
- streaming 응답
- UI
- 다중 사용자 인증/RBAC
- OpenAI 실제 호출을 포함한 통합 테스트
- Agent graph 자체 재작성
- SQL 생성 품질 고도화
- Backend profile/context 추론 로직 고도화

## Architecture

전체 구조는 다음과 같다.

```text
User
  -> CLI 또는 HTTP /agent/ask
  -> AgentRuntime
  -> BackendToolProvider
  -> Backend Tool Contract
     - run_create
     - datasource_list
     - datasource_create
     - datasource_test
     - datasource_refresh_catalog
     - datasource_get_catalog_summary
     - analysis_build_context
     - datasource_query
  -> Backend Services
  -> SQLite / artifacts / datasource / policy
```

`AgentRuntime`은 tool provider가 MCP stdio인지 in-process adapter인지 알 필요가 없다. runtime은 `dict[str, Any]` 형태의 raw backend tools를 받아 기존 `build_agent_tools()`로 LangChain tool을 만들고 agent를 실행한다.

CLI 경로:

```text
data-agent-agent CLI
  -> AgentRuntime
  -> MCP stdio BackendToolProvider
  -> data-agent-mcp
  -> BackendServices
```

HTTP API 경로:

```text
FastAPI /agent/ask
  -> AgentRuntime
  -> InProcessBackendToolProvider
  -> MCP tool wrapper functions with services
  -> BackendServices
```

## Components

### `data_agent_agent.runtime`

공통 실행 흐름을 담당한다.

- `AgentRunRequest`
  - `question`
  - `datasource_id`
  - `model`
  - `row_limit`
  - `metadata`

- `AgentRunResult`
  - `answer`
  - `run_id`
  - `datasource_id`
  - `raw_result`

- `AgentRuntime`
  - backend tools 로딩
  - 필수 tool 검증
  - datasource 준비
  - `run_create`
  - agent tool build
  - agent invoke
  - 최종 답변 추출

기존 `run_cli()`의 핵심 로직은 이 runtime으로 이동한다.

### `data_agent_agent.tool_provider`

Backend 연결 방식을 추상화한다.

- `MCPBackendToolProvider`
  - 기존 `load_backend_tools(config)` 로직을 사용한다.
  - CLI 기본 provider다.

- `InProcessBackendToolProvider`
  - `BackendServices`를 받아 MCP tool wrapper 함수들을 raw tool처럼 노출한다.
  - HTTP API 기본 provider다.
  - wrapper 함수에는 항상 `services=services`를 주입한다.

두 provider는 동일한 tool name 집합을 반환해야 한다.

### `data_agent_agent.runner`

CLI 어댑터로 축소한다.

- argparse 처리
- `AgentConfig.from_env(...)`
- `AgentRuntime` 생성
- 결과 출력
- CLI 오류 메시지 출력

### `data_agent_backend.api.routes_agent`

HTTP API 표면을 제공한다.

`POST /agent/ask`

요청:

```json
{
  "question": "월별 주문 수를 알려줘",
  "datasource_id": "ds_...",
  "model": "gpt-5.5-mini",
  "row_limit": 1000,
  "metadata": {}
}
```

응답:

```json
{
  "ok": true,
  "data": {
    "answer": "...",
    "run_id": "run_...",
    "datasource_id": "ds_..."
  },
  "error": null
}
```

`datasource_id`가 없으면 CLI와 동일하게 `.env`의 `DATA_AGENT_MYSQL_*` 값으로 datasource를 찾거나 생성한다.

## Data Flow

1. 사용자가 CLI 또는 HTTP API로 질문을 전달한다.
2. runtime이 config와 tool provider를 준비한다.
3. `datasource_id`가 있으면 그대로 사용한다.
4. `datasource_id`가 없으면 `.env` 기반 MySQL payload를 만들고 기존 datasource를 재사용하거나 새로 생성한다.
5. datasource connection test와 catalog refresh를 수행한다.
6. `run_create`를 호출하고 question, datasource id, source metadata를 기록한다.
7. `build_agent_tools()`가 `get_catalog_summary`, `build_analysis_context`, `run_sql`을 구성한다.
8. Deep Agent를 호출한다.
9. 최종 답변, run id, datasource id를 반환한다.
10. SQL query/result artifact와 run event는 기존 Backend 도구 흐름을 통해 기록된다.

## Error Handling

CLI는 사용자에게 짧은 오류 메시지를 출력하고 exit code 1로 종료한다.

HTTP API는 기존 Backend API와 같이 항상 `ToolResult` envelope를 반환한다.

대표 오류:

- `OPENAI_API_KEY` 누락: validation/config error
- MySQL env 누락: validation/config error
- datasource 연결 실패: backend datasource error
- 필수 backend tool 누락: backend tool error
- SQL 정책 차단: backend policy error
- Agent 실행 예외: agent runtime error

HTTP 응답의 error code는 가능한 한 기존 `BackendError` code를 유지한다. Agent Layer 내부 오류는 `AGENT_RUNTIME_ERROR`로 감싼다.

## Testing

테스트는 실제 OpenAI API를 호출하지 않는다.

추가/갱신 테스트:

- 공통 runtime이 explicit datasource id를 사용할 때 datasource create/test/refresh를 건너뛰는지 확인
- 공통 runtime이 env datasource를 생성/재사용하고 refresh한 뒤 run을 만드는지 확인
- CLI가 runtime을 호출하는 얇은 어댑터인지 확인
- in-process provider가 필수 backend tool names를 제공하는지 확인
- `/agent/ask`가 `ToolResult` envelope로 answer, run id, datasource id를 반환하는지 확인
- config/runtime 오류가 HTTP에서 실패 envelope로 정규화되는지 확인

전체 검증 명령:

```powershell
uv run pytest -q
```

## Future Extensions

이번 설계는 이후 고도화를 막지 않는다.

- Backend는 `analysis_build_context`, profile inference, semantic registry, policy/approval을 독립적으로 고도화할 수 있다.
- Agent Layer는 prompt, model, DeepAgents/LangGraph 구현, SQL retry loop, multi-step planning을 독립적으로 고도화할 수 있다.
- HTTP API는 이후 background run, event polling, streaming, artifact browsing API로 확장할 수 있다.
- MCP stdio provider는 추후 remote MCP provider로 교체할 수 있다.

핵심 유지 조건은 Agent가 Backend 내부 service 객체를 직접 사용하지 않고 backend tool contract를 통해서만 접근하는 것이다.
