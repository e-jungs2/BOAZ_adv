# Python 샌드박스 timeout 및 실행 안정화 설계

## 목표

Python 샌드박스 실행이 잘못된 코드나 환경 문제로 장시간 멈춰 보이는 상황을 방지한다. SQL 실행 제한과 Python 실행 제한은 분리하고, Python 분석 작업은 기본적으로 안전하게 제한하되 사용자가 명시적으로 더 긴 실행 시간을 요청할 수 있게 한다.

## 배경

최근 agent 실행에서 SQL 쿼리는 완료됐지만 `sandbox_run_python` 단계가 오래 지속되어 사용자가 강제 중지했다. 로컬 실행 기록을 확인하면 SQL 결과 artifact는 생성됐고, 이후 Python sandbox run 디렉터리만 남아 종료 로그가 등록되지 않았다. 이전 30초 timeout은 분석/시각화에는 짧았고, timeout을 완전히 해제하면 잘못된 Python 실행이 30분 가까이 지속될 수 있다.

따라서 필요한 개선은 단순히 timeout을 없애는 것이 아니라 다음을 동시에 만족해야 한다.

- 기본 실행은 오래 멈추지 않는다.
- 긴 분석은 사용자가 명시적으로 허용할 수 있다.
- 실행이 시작됐다는 최소 로그는 강제 중지 전에도 남는다.
- Python 코드 실패는 agent가 한 번 수정 재시도할 수 있다.
- 분석 패키지 환경은 명확한 설치 경로를 가진다.

## 범위

포함한다.

- Python sandbox 기본 timeout을 5분으로 설정
- Python sandbox 최대 timeout을 10분으로 설정
- API, MCP, agent tool, CLI를 통한 `timeout_ms` 전달
- timeout 값 validation
- Python 실행 시작/종료 로그
- agent system prompt 기반 1회 재시도 규칙
- `analysis` optional dependency 추가
- `DATA_AGENT_LOCAL_PYTHON_EXECUTABLE` 보조 경로 문서화 및 유지

포함하지 않는다.

- Python 코드 prelude 주입
- `import os` 누락 같은 코드 정적 검사
- backend가 Python 코드를 자동 수정하는 기능
- streaming stdout/stderr
- background job 또는 실행 취소 API
- SQL 쿼리 성능 개선

## 결정 사항

### Timeout 정책

Python sandbox는 기본 실행 timeout을 `300_000ms`로 둔다. 사용자가 명시적으로 timeout을 늘릴 수 있지만 최대값은 `600_000ms`로 제한한다.

- `timeout_ms`가 생략되면 기본값 5분을 사용한다.
- `timeout_ms <= 0`이면 `VALIDATION_ERROR`를 반환한다.
- `timeout_ms > 600_000`이면 `VALIDATION_ERROR`를 반환한다.
- SQL datasource query timeout은 기존 설정과 분리한다.

이 정책은 local sandbox와 docker sandbox 모두에 동일하게 적용한다.

### Timeout 전달 경로

다음 인터페이스가 `timeout_ms`를 받는다.

- HTTP `/execution/python`
- MCP `sandbox_run_python`
- agent tool `run_python`
- CLI `data-agent-agent --python-timeout-ms`

CLI에서 받은 `--python-timeout-ms`는 agent runtime을 거쳐 `build_agent_tools()`의 기본 Python timeout으로 전달된다. agent가 tool 호출에서 별도 timeout을 지정하지 않으면 CLI 기본값을 사용한다.

### Validation 위치

timeout validation은 backend service 실행 경계에서 수행한다. API, MCP, agent, CLI는 값을 전달할 수 있지만 최종 정책 enforcement는 sandbox executor가 맡는다. 이렇게 하면 호출 경로가 늘어나도 같은 제한을 공유한다.

상한 초과나 0 이하 값은 자동 보정하지 않는다. 사용자가 요청한 값이 실행되지 않았다는 사실을 명확히 알 수 있도록 `VALIDATION_ERROR`를 반환한다.

### 실행 로그

Python sandbox는 실행 시작 시점에 시작 로그를 남긴다.

시작 로그에는 다음 정보를 포함한다.

- `execution_id`
- `run_id`
- `sandbox_backend`
- `timeout_ms`
- `input_artifact_ids`
- `code_path`
- `started_at`
- `status: running`

정상 종료, 비정상 종료, timeout이 발생하면 종료 로그를 남긴다.

종료 로그에는 다음 정보를 포함한다.

- `execution_id`
- `status`
- `exit_code`
- `runtime_ms`
- `stdout` 또는 snippet
- `stderr` 또는 snippet
- `error_message`
- `finished_at`
- 생성 artifact 목록

강제 중지나 프로세스 종료로 artifact 등록까지 가지 못하더라도 run 디렉터리의 `logs` 아래에서 시작 로그를 확인할 수 있어야 한다.

### Agent 재시도

자동 재시도는 backend가 아니라 agent layer에서 처리한다. 현재 DeepAgents 구조에서는 tool wrapper가 LLM을 직접 재호출하지 않으므로, 강제 orchestration 대신 system prompt 규칙으로 처리한다.

규칙은 다음과 같다.

- `run_python` 결과가 `status=error`이면 `stderr`와 `error_message`를 읽고 코드를 수정해 최대 1회만 재실행한다.
- `status=timeout`이면 같은 코드를 자동 재시도하지 않는다.
- 재시도 후에도 실패하면 최종 답변에 실패 원인과 다음 조치가 드러나야 한다.

`ModuleNotFoundError`, `NameError`, `FileNotFoundError`, `SyntaxError` 같은 일반 Python 오류는 재시도 대상이다. timeout은 재시도 대상이 아니다.

### 분석 패키지 환경

`pyproject.toml`에 `analysis` optional dependency를 추가한다.

초기 패키지는 다음으로 둔다.

- `pandas`
- `matplotlib`
- `seaborn`

개발자는 분석 샌드박스가 필요한 경우 다음처럼 설치한다.

```powershell
uv sync --extra dev --extra analysis
```

local sandbox는 기본적으로 backend/agent 프로세스의 Python을 사용한다. 다른 Python 환경을 쓰고 싶으면 기존 설정인 `DATA_AGENT_LOCAL_PYTHON_EXECUTABLE`로 분석 패키지가 설치된 Python 실행 파일을 지정한다.

## 데이터 흐름

1. 사용자가 CLI 또는 API로 분석 질문을 보낸다.
2. agent runtime이 datasource와 run을 준비한다.
3. agent가 SQL로 원자료 또는 집계 결과를 생성한다.
4. agent가 `run_python`을 호출한다.
5. `timeout_ms`가 지정되지 않았으면 기본 5분을 사용한다.
6. backend sandbox executor가 timeout 값을 검증한다.
7. executor가 run 디렉터리와 시작 로그를 만든다.
8. local 또는 docker Python 실행을 시작한다.
9. 실행이 끝나면 출력 파일을 artifact로 등록하고 종료 로그를 남긴다.
10. 실패 결과가 agent에 반환되면 agent는 prompt 규칙에 따라 일반 오류에 한해 한 번 수정 재시도한다.

## 오류 처리

timeout validation 실패:

- `ToolResult.ok = false`
- `error.code = "VALIDATION_ERROR"`
- details에 `timeout_ms`, `max_timeout_ms` 포함

Python timeout:

- `ExecutionResult.status = "timeout"`
- `error_message = "Python sandbox execution timed out."`
- agent는 자동 재시도하지 않는다.

Python 일반 오류:

- `ExecutionResult.status = "error"`
- `exit_code`와 stderr를 보존한다.
- agent는 최대 1회 재시도한다.

샌드박스 비활성:

- 기존 `sandbox_not_configured` 계약을 유지한다.

## 테스트 전략

단위 테스트:

- 기본 `ExecutionLimits()`는 timeout을 비워 두고 executor가 config 기본값 5분을 적용한다.
- 명시 `timeout_ms`는 config 기본값보다 우선한다.
- 0 이하 timeout은 `VALIDATION_ERROR`를 반환한다.
- 최대 timeout 초과는 `VALIDATION_ERROR`를 반환한다.
- local executor timeout 시 `ExecutionStatus.timeout`을 반환한다.
- docker provider 요청에 검증된 timeout이 전달된다.
- 시작 로그가 subprocess 실행 전에 생성된다.
- 종료 로그가 success, error, timeout 경로에서 생성된다.

API/MCP 테스트:

- `/execution/python`이 `timeout_ms`를 받는다.
- `sandbox_run_python_impl`이 `ExecutionLimits(timeout_ms=...)`를 전달한다.
- MCP public signature에서 `services`는 숨기고 `timeout_ms`는 노출한다.

Agent/CLI 테스트:

- `run_python` agent tool이 `timeout_ms`를 raw tool에 전달한다.
- CLI `--python-timeout-ms`가 runtime과 tool 기본 timeout으로 전달된다.
- system prompt에 Python 실패 시 1회 재시도, timeout 재시도 금지 규칙이 포함된다.

검증 명령:

```powershell
uv run pytest -q
```

## 완료 기준

- Python sandbox 기본 실행은 5분 후 timeout 된다.
- 사용자는 CLI/API/MCP/agent tool 경로에서 timeout을 명시적으로 지정할 수 있다.
- 10분 초과 요청은 실행 전에 실패한다.
- Python 실행 시작 로그가 남아 강제 중지 후에도 어떤 실행이 시작됐는지 확인할 수 있다.
- Python 일반 오류에 대한 1회 재시도 규칙이 agent system prompt에 반영된다.
- 분석 패키지는 `analysis` extra로 설치할 수 있다.
