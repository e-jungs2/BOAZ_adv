# MCP/API Contract 및 Agent Runtime 안정화 설계

## 목표

MCP/API 계약을 먼저 고정하고, 그 계약 위에서 CLI/Agent runtime을 안정화한다. 외부 HTTP path, MCP tool 이름, 기본 `ToolResult` 응답 형태는 유지하면서 내부 wrapper 패턴, 오류 details, datasource bootstrap, trace/run metadata를 더 명확하게 만든다.

이번 작업은 새로운 분석 기능 추가가 아니라 제품화 전 안정화 작업이다. 특히 앞으로 DeepAgents가 아닌 LangGraph 기반 Agent가 붙을 수 있으므로, `data_agent_agent`는 특정 agent 구현체가 아니라 Agent runtime shell과 adapter 계층으로 정리한다.

## 결정 사항

- 기존 HTTP path, MCP tool 이름, 기본 payload 이름은 유지한다.
- HTTP와 MCP 응답은 계속 `{ ok, data, error }` 형태의 `ToolResult` envelope를 따른다.
- `error.details`, run metadata, trace 이름 같은 부가 필드는 확장할 수 있다.
- MCP public tool 함수와 내부 `_impl(..., services)` 함수 패턴을 고정한다.
- MCP public schema에는 내부 DI용 `services` 인자가 노출되지 않아야 한다.
- HTTP route는 얇은 변환 계층으로 유지하고, validation/backend/unexpected error를 `ToolResult`로 감싼다.
- `data_agent_agent`는 Agent 구현체가 아니라 runtime shell로 본다.
- 현재 DeepAgents 실행은 adapter로 감싸고, 이후 LangGraph adapter가 같은 경계로 들어올 수 있게 한다.
- 사용자에게 보이는 CLI/API 오류 메시지는 한국어로 명확하게 유지하고, 기계가 읽을 수 있는 details를 함께 보존한다.

## 범위

포함 범위:

- `ToolResult` 성공/실패 계약 테스트 보강
- `BackendError` details 보존과 unknown exception masking 확인
- MCP public wrapper와 `_impl(..., services)` 패턴 테스트 보강
- MCP tool schema에서 `services` 인자 노출 방지 확인
- HTTP validation/backend/unexpected error envelope 테스트 보강
- `normalize_tool_result()` 입력 형태별 표준화 테스트 보강
- Agent 실행 adapter 경계 도입
- datasource bootstrap 단계 이름과 실패 details 정리
- env/model/api-key/row-limit 오류 처리 정리
- `/agent/ask` 실패 응답의 details 확장
- LangSmith trace naming과 run metadata 규칙 정리
- 기존 CLI와 DeepAgents 실행 경로 유지

제외 범위:

- HTTP path 변경
- MCP tool 이름 변경
- response envelope의 호환성을 깨는 변경
- LangGraph agent 구현 자체 추가
- datasource/analysis backend 대규모 분리
- streaming/background run API
- OpenAI 실제 호출을 포함한 통합 테스트

## 아키텍처

안정화 후 책임 경계는 다음과 같다.

```text
HTTP / MCP client
  -> API routes 또는 MCP public tools
  -> ToolResult contract
  -> BackendServices

CLI 또는 /agent/ask
  -> AgentRuntime
  -> BackendToolProvider
  -> Backend tool contract
  -> AgentRunner adapter
  -> DeepAgents 현재 구현 또는 향후 LangGraph 구현
```

`data_agent_backend.models.tool_results`는 모든 HTTP/MCP 결과의 표준 envelope를 담당한다. 성공은 `ok=true`, 실패는 `ok=false`와 `ToolError`를 사용한다. `error.details`는 확장 가능하지만 `code`, `message`, `details` 필드는 유지한다.

`data_agent_backend.mcp`는 public 함수와 `_impl` 함수를 분리한다. public 함수는 MCP schema에 노출되는 얇은 wrapper이고, `_impl` 함수는 테스트와 in-process 호출에서 `BackendServices`를 주입받는 내부 진입점이다.

`data_agent_backend.api`는 요청/응답 변환만 담당한다. 비즈니스 로직과 정책 판단은 서비스 계층에 둔다. validation error와 unexpected error도 raw FastAPI 응답이 아니라 `ToolResult` envelope로 내려간다.

`data_agent_agent`는 backend 계약을 소비하는 runtime shell이다. runtime은 config/env 해석, datasource bootstrap, run 생성, tool provider 준비, trace/run metadata 구성을 담당한다. 실제 agent framework의 raw result shape 처리는 `AgentRunner` adapter 내부로 이동하거나 fallback 유틸로 격리한다.

## Contract Hardening 설계

외부 계약:

- HTTP와 MCP 응답은 항상 `ToolResult` envelope를 따른다.
- 기존 path, tool 이름, 기본 payload 이름은 유지한다.
- `error.details`에는 `suggestion`, `retryable`, `bootstrap_step`, `missing_env_vars`, `decision_id`, `query_artifact_id` 같은 부가 정보를 담을 수 있다.
- validation error는 `VALIDATION_ERROR` 코드로 표준화한다.

내부 패턴:

- MCP public 함수는 내부 `services` 인자를 schema에 노출하지 않는다.
- `_impl(..., services: BackendServices)` 함수는 실제 테스트 가능한 진입점이다.
- public 함수는 `get_services()`로 기본 서비스를 주입하고 `_impl`에 위임한다.
- `_impl` 함수는 service 메서드를 호출하고 `result_wrap()`으로 예외를 `ToolResult`에 매핑한다.

테스트 기준:

- 모든 MCP public tool signature/schema에 `services`가 없는지 검사한다.
- 대표 tool의 `_impl`이 주입된 `services`를 사용하는지 검사한다.
- `create_mcp_server()`가 schema 오류 없이 tool을 등록하는지 검사한다.
- `ToolResult.from_exception()`이 `BackendError` details를 보존하는지 검사한다.
- unknown exception은 내부 메시지를 과하게 노출하지 않고 `INTERNAL_ERROR`로 매핑하는지 확인한다.
- `normalize_tool_result()`가 MCP text block JSON, model_dump 객체, plain dict, 실패 envelope, plain string을 안정적으로 처리하는지 확인한다.

## Agent Runtime 안정화 설계

`AgentRuntime`은 특정 agent framework를 모르는 실행 shell로 유지한다.

주요 책임:

- config/env 해석
- datasource id 결정
- env 기반 datasource 생성 또는 기존 datasource 재사용
- datasource test
- catalog refresh
- run 생성
- backend tools를 agent tools로 변환
- trace/run metadata 구성
- agent adapter 호출
- 사용자 친화적 오류 변환

`AgentRunner` adapter 경계:

- 입력은 `question`, `model`, `tools`, `metadata` 또는 trace context이다.
- 출력은 표준화된 `answer`, `raw_result`이다.
- 현재 DeepAgents 실행은 기본 adapter가 담당한다.
- 향후 LangGraph adapter는 같은 interface를 구현한다.
- `extract_final_content()`는 runtime 본체가 아니라 adapter 또는 fallback 유틸 책임으로 격리한다.

Datasource bootstrap 단계:

```text
config_load
datasource_resolve
datasource_list
datasource_create
datasource_test
datasource_refresh_catalog
run_create
agent_invoke
```

각 단계 실패 시 `AgentRuntimeError`는 다음 정보를 보존한다.

- `bootstrap_step`
- backend `code`
- backend `message`
- `suggestion`
- `retryable`
- 관련 datasource/run 정보

오류 경험:

- `OPENAI_API_KEY` 누락은 명확한 한국어 메시지로 반환한다.
- MySQL env 누락은 `missing_env_vars` details에도 담는다.
- row limit 오류는 CLI/API 모두에서 같은 의미로 전달한다.
- `/agent/ask`는 기존 `AGENT_CONFIG_ERROR`, `AGENT_RUNTIME_ERROR` 코드를 유지하되 details를 확장한다.
- CLI는 내부 details 중 사람이 볼 만한 핵심 정보를 간결하게 출력한다.

Trace/run metadata:

- trace name 규칙은 `data-agent:{source}:{datasource_id}:{run_id}`로 둔다.
- run metadata에는 `source`, `model`, `datasource_source`, `datasource_id`, `question`, `trace_name`을 포함한다.
- LangSmith 관련 환경변수가 꺼져 있어도 runtime 동작에는 영향이 없어야 한다.

## 작업 순서

1단계는 MCP/API contract hardening이다.

- `ToolResult` 계약 테스트 보강
- MCP wrapper/schema 테스트 보강
- HTTP error envelope 테스트 보강
- `normalize_tool_result()` 테스트 보강
- 기존 route/tool 이름 유지 확인
- 전체 테스트 실행

2단계는 CLI/Agent runtime 안정화이다.

- Agent 실행 adapter 경계 도입
- datasource bootstrap 단계 명시화
- runtime error details 확장
- trace/run metadata 정리
- CLI/API 사용자 오류 메시지 보강
- adapter 교체 가능성 테스트
- 전체 테스트 실행

## 완료 기준

- 기존 HTTP path와 MCP tool 이름이 유지된다.
- 모든 HTTP/MCP 실패 응답이 `ToolResult` shape이다.
- MCP public schema에 `services`가 노출되지 않는다.
- Agent runtime은 DeepAgents raw result shape에 직접 강하게 묶이지 않는다.
- 향후 LangGraph adapter를 추가할 수 있는 접점이 생긴다.
- datasource bootstrap 실패 단계가 구분되어 보고된다.
- CLI/API 오류 메시지가 더 명확하고, details가 손실되지 않는다.
- `uv run pytest -q`가 통과한다.

## 검증

기본 검증 명령:

```powershell
uv run pytest -q
```

서버 실행은 장시간 프로세스이므로 자동 검증은 import, schema registration, route response, runtime fake adapter 테스트를 중심으로 한다. 필요하면 수동 smoke check로 `uv run data-agent-mcp`, `uv run data-agent-api`를 별도 터미널에서 확인한다.
