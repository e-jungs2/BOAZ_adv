# Python 기반 분석 실행 하이브리드 설계

## 목표

데이터 분석 에이전트가 SQL 결과를 받은 뒤 Python으로 후처리, 통계 계산, 시각화, 파일 생성을 수행할 수 있게 한다. 1차 구현은 로컬 개발 환경에서 승인 없이 바로 실행되는 Python runner를 제공하고, 이후 Docker sandbox로 확장할 수 있도록 MCP/API와 agent tool 계약은 처음부터 공통 인터페이스로 유지한다.

## 배경

현재 백엔드에는 `sandbox_run_python` MCP/API 도구와 `DockerSandboxExecutor`가 이미 있다. Docker 실행기는 입력 artifact 복사, 실행 로그 생성, 생성 파일 artifact 등록까지 담당한다. 하지만 기본 설정은 `sandbox_enabled=False`이고 `sandbox.python.run`은 승인 ID 없이는 `approval_required`를 반환한다. 또한 CLI 에이전트가 사용하는 `build_agent_tools()`에는 Python 실행 도구가 노출되어 있지 않다.

따라서 현재 상태는 "백엔드 내부 실행기 골격은 존재하지만 에이전트 분석 루프에서는 Python을 쓸 수 없는 상태"다.

## 범위

포함한다.

- 설정 기반 `disabled | local | docker` sandbox backend 선택
- 로컬 개발용 Python 실행기 추가
- 로컬 개발 모드에서 `sandbox.python.run` 승인 없이 실행 허용
- MCP/API의 기존 `sandbox_run_python` 계약 유지
- 에이전트 도구 목록에 Python 실행 도구 추가
- SQL 결과 artifact를 Python 입력으로 받아 후처리할 수 있는 흐름
- Python이 생성한 CSV, JSON, PNG, HTML, MD, TXT 등 파일의 artifact 등록
- 실행 로그 artifact 생성
- 로컬 runner와 정책, MCP/API, agent tool 테스트

포함하지 않는다.

- Docker 설치 자동화
- 패키지 설치 도구 허용
- 네트워크 접근 허용
- 원격 코드 실행 서비스
- 분석 품질 개선용 SQL 프롬프트 개편
- 장시간 background job, streaming execution, notebook UI

## 결정 사항

설정 기반 하이브리드 방식을 사용한다.

- 기본값은 안전하게 `disabled`로 둔다.
- 개발 환경에서는 명시적으로 `local`을 켜면 승인 없이 Python이 실행된다.
- 추후 격리 환경에서는 같은 도구 계약으로 `docker` backend를 사용한다.
- 에이전트는 실행 backend가 local인지 docker인지 알 필요 없이 `run_python` 도구를 호출한다.

## 설정 설계

`BackendConfig`에 새 필드를 추가한다.

- `sandbox_backend: Literal["disabled", "local", "docker"] = "disabled"`
- `local_python_executable: Path | None = None`

호환성을 위해 기존 `sandbox_enabled`는 당장 제거하지 않는다. `sandbox_backend`가 명시되지 않은 기존 흐름에서는 다음 규칙을 적용한다.

- `sandbox_backend == "docker"`이면 `DockerSandboxExecutor`
- `sandbox_backend == "local"`이면 `LocalPythonSandboxExecutor`
- `sandbox_backend == "disabled"`이고 `sandbox_enabled=True`이면 기존 호환 경로로 `DockerSandboxExecutor`
- 그 외에는 `DisabledSandboxExecutor`

MCP/API 프로세스에서 실제로 local 모드를 켜기 쉬워야 하므로 기본 서비스 생성 경로는 `.env`와 환경 변수를 읽어야 한다. `BackendConfig.from_env(load_env=True)`를 추가하고, `create_backend_services(config=None)`는 이 메서드로 기본 설정을 만든다. 테스트처럼 명시적 `BackendConfig`를 주입하는 경로는 기존처럼 그대로 사용한다.

읽을 환경 변수:

- `DATA_AGENT_SANDBOX_BACKEND=disabled|local|docker`
- `DATA_AGENT_LOCAL_PYTHON_EXECUTABLE=<path>`

`.env.example`에는 기본값 예시를 추가하되 안전하게 `DATA_AGENT_SANDBOX_BACKEND=disabled`로 둔다. 로컬 개발자가 Python 실행을 열 때만 `local`로 바꾼다.

## 정책 설계

`sandbox.python.run` 정책은 실행 backend와 실행 목적에 따라 다르게 판단한다.

- `disabled`: 기존처럼 승인 필요 또는 비활성 결과를 반환한다.
- `local`: 개발 모드로 간주하고 승인 없이 허용한다.
- `docker`: 기존 정책과 동일하게 승인 ID를 요구하는 방향을 유지한다.

정책 엔진이 현재 `BackendConfig`를 직접 알지 못하므로 두 가지 중 하나를 선택한다.

1. `PolicyContext` 또는 policy payload에 `sandbox_backend`과 `dev_mode`를 넣고 `PolicyEngine`이 판단한다.
2. `LocalPythonSandboxExecutor`가 별도 action인 `sandbox.python.run.local`을 평가한다.

추천은 1번이다. 기존 action 이름을 유지하면 policy audit, MCP/API, agent tool 계약이 단순해진다. executor가 `payload={"sandbox_backend": "local", ...}`을 넣고, `PolicyEngine`은 이 값이 `local`이면 승인 없이 허용한다.

## LocalPythonSandboxExecutor 설계

새 실행기는 `SandboxExecutor` 프로토콜을 그대로 구현한다.

실행 흐름:

1. `execution_id`를 생성한다.
2. `sandbox.python.run` 정책을 평가한다. payload에는 code size, input artifact ids, `sandbox_backend="local"`을 포함한다.
3. `.data_agent/sandbox/runs/<execution_id>/` 아래에 실행 디렉터리를 만든다.
4. 하위 디렉터리를 만든다.
   - `code/run.py`
   - `inputs/<artifact_id>/<filename>`
   - `workspace/`
   - `outputs/`
   - `logs/`
5. 입력 artifact 파일을 `inputs` 아래로 복사한다.
6. 현재 Python 실행 파일 또는 `local_python_executable`로 `run.py`를 subprocess 실행한다.
7. 실행 환경 변수로 다음 경로를 제공한다.
   - `DATA_AGENT_INPUTS_DIR`
   - `DATA_AGENT_WORKSPACE_DIR`
   - `DATA_AGENT_OUTPUTS_DIR`
   - `DATA_AGENT_EXECUTION_ID`
8. subprocess의 working directory는 `workspace`로 둔다.
9. timeout은 `ExecutionLimits.timeout_ms` 또는 기본값을 사용한다.
10. 실행 전후 snapshot을 비교해 `workspace`와 `outputs`에 새로 생기거나 변경된 파일을 artifact로 등록한다.
11. stdout, stderr, exit_code, runtime, 생성 artifact 목록을 execution log artifact로 등록한다.
12. `ExecutionResult`를 반환한다.

로컬 runner는 격리 장치가 아니다. 파일시스템과 설치 패키지 접근이 현재 프로세스 권한에 묶이므로 개발 모드 전용으로 문서화한다.

## Artifact 규칙

Docker 실행기의 기존 규칙과 동일하게 유지한다.

- `.csv`, `.tsv`, `.json`, `.jsonl`, `.parquet` -> `dataset`
- `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp` -> `chart`
- `.md`, `.markdown`, `.txt`, `.html` -> `report`
- 기타 -> `file`

생성 artifact metadata에는 다음 값을 포함한다.

- `execution_id`
- `sandbox_backend`
- `sandbox_root`
- `sandbox_relative_path`
- `format`

입력 artifact와 생성 artifact 사이에는 `generated_by_python` lineage를 남긴다. 실행 로그 artifact는 `execution_log_for` edge를 사용한다.

## Agent Tool 설계

`data_agent_agent.tools.build_agent_tools()`에 `run_python` 도구를 추가한다.

입력:

- `code: str`
- `input_artifact_ids: list[str] | None = None`

출력:

- `execution_id`
- `status`
- `exit_code`
- `stdout`
- `stderr`
- `runtime_ms`
- `created_artifact_ids`
- `error_message`

도구 설명은 에이전트가 다음 규칙을 따르도록 작성한다.

- SQL은 원자료 추출과 DB 집계에 사용한다.
- Python은 SQL 결과 artifact를 입력으로 받아 후처리, 통계, 시각화, 파일 생성을 할 때 사용한다.
- 생성 파일은 `DATA_AGENT_OUTPUTS_DIR` 또는 현재 작업 디렉터리 아래에 저장한다.
- 파일 경로는 환경 변수로 받은 디렉터리를 사용한다.
- 네트워크 호출이나 패키지 설치를 시도하지 않는다.

`REQUIRED_BACKEND_TOOLS`에는 `sandbox_run_python`을 추가한다. 기존 MCP 서버에는 이미 tool이 등록되어 있으므로 agent layer의 필수 도구 검증과 wrapper만 보강하면 된다.

## 프롬프트 설계

시스템 프롬프트에 Python 사용 규칙을 추가한다.

- SQL 결과가 표본만으로 부족하거나 계산/시각화가 필요한 경우 `run_python`을 사용한다.
- `run_sql`이 반환한 `artifact_ref.artifact_id`를 `run_python`의 `input_artifact_ids`로 넘긴다.
- Python 코드에서는 입력 파일을 `DATA_AGENT_INPUTS_DIR`에서 찾는다.
- 차트나 보고서는 `DATA_AGENT_OUTPUTS_DIR`에 저장한다.
- 최종 답변에는 생성 artifact id와 해석 가능한 요약을 함께 제공한다.

기존 SQL 분석 품질 개선은 이번 범위에서 제외하되, Python 도구 사용법은 명확히 안내한다.

## 오류 처리

로컬 실행 오류는 `ExecutionResult.status`로 표현한다.

- 정상 종료: `success`
- 비정상 exit code: `error`
- timeout: `timeout`
- 정책 차단: `policy_blocked`
- 비활성 backend: `sandbox_not_configured`

subprocess가 실패해도 stdout/stderr와 실행 로그 artifact는 가능한 한 남긴다. artifact 등록 중 오류가 나면 `ExecutionStatus.error`와 `error_message`를 반환한다.

timeout이 발생하면 프로세스를 종료하고 stderr/stdout 일부를 보존한다.

## 테스트 전략

단위 테스트:

- `sandbox_backend=local`이면 factory가 `LocalPythonSandboxExecutor`를 선택한다.
- local backend에서는 approval ID 없이 `sandbox.python.run`이 허용된다.
- local runner가 stdout/stderr/exit_code/runtime을 반환한다.
- local runner가 `outputs`에 생성한 CSV/PNG/MD 파일을 artifact로 등록한다.
- 입력 artifact가 `inputs` 디렉터리로 복사되고 Python 코드에서 읽을 수 있다.
- timeout 시 `ExecutionStatus.timeout`을 반환한다.
- `sandbox_backend=disabled`의 기존 비실행 계약은 유지된다.
- Docker executor의 기존 승인 필요 계약은 유지된다.

MCP/API 테스트:

- `/execution/python`이 local backend에서 성공 결과를 반환한다.
- `sandbox_run_python_impl`이 ToolResult envelope를 유지한다.
- MCP public signature에서 `services`가 노출되지 않는다.

Agent layer 테스트:

- `REQUIRED_BACKEND_TOOLS`에 `sandbox_run_python`이 포함된다.
- `build_agent_tools()`가 `run_python` 도구를 만든다.
- `run_python` wrapper가 raw MCP tool을 호출하고 normalized result를 반환한다.
- approval_required나 error envelope를 agent-friendly payload로 변환한다.

검증 명령:

```powershell
uv run pytest -q
```

전체 테스트가 오래 걸리면 우선 다음 범위를 실행한다.

```powershell
uv run pytest -q tests/test_sql_sandbox_mcp.py tests/test_agent_layer.py tests/test_http_api.py
```

## 완료 기준

- 개발 설정에서 local Python backend를 켜면 승인 없이 Python 코드가 실행된다.
- 에이전트가 SQL 결과 artifact id를 Python 도구 입력으로 넘길 수 있다.
- Python이 만든 파일이 artifact로 등록되고 lineage가 남는다.
- 기존 disabled/Docker 계약이 깨지지 않는다.
- MCP/API 응답은 기존 `ToolResult` envelope를 유지한다.
- 관련 테스트가 통과한다.
