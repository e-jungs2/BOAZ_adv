# 저장소 지침

항상 한국어로 답변해 주세요. 작업 관련 문서도 한국어로 작성해 주세요.

## 프로젝트 구조 및 모듈 구성

이 저장소는 LangGraph/DeepAgents 기반 데이터 분석 에이전트를 위한 Python 3.11+ 패키지입니다. 핵심 코드는 `src/` 아래에 있으며, 백엔드 실행 계층은 `data_agent_backend`, CLI/DeepAgents 에이전트 계층은 `data_agent_agent`가 담당합니다.

- `pyproject.toml`: 패키지 메타데이터, 런타임 의존성, pytest 설정, 콘솔 스크립트(`data-agent-api`, `data-agent-mcp`, `data-agent-agent`)를 정의합니다.
- `.env.example`: OpenAI, MySQL datasource, Python sandbox backend 설정 예시입니다. 실제 secret은 `.env`에 두고 커밋하지 마세요.
- `src/data_agent_backend/config.py`: `.data_agent/` 기반 런타임 디렉터리, SQL/datasource 제한, Python sandbox backend(`disabled`, `local`, `docker`), Docker sandbox, 네트워크, 패키지 설치 정책을 정의합니다. 기본 서비스 생성은 `BackendConfig.from_env()`를 통해 `.env`/환경변수를 읽습니다.
- `src/data_agent_backend/api/`: FastAPI HTTP API 계층입니다. `app.py`는 `data-agent-api` 콘솔 스크립트 대상이며 `/health`, `/workspace`, `/agent`, `/analysis-context`, `/runs`, `/artifacts`, `/memory`, `/approvals`, `/policy`, `/execution`, `/catalog`, `/datasources`, `/exports` 라우터를 등록합니다.
- `src/data_agent_backend/mcp/`: MCP 서버와 tool wrapper 계층입니다. `server.py`는 `data-agent-mcp` 콘솔 스크립트 대상이며 workspace, analysis context/profile/semantic, run, artifact, memory, approval, policy, SQL/Python execution, catalog, datasource, export 도구를 등록합니다.
- `src/data_agent_backend/models/`: HTTP API, MCP 도구, 서비스가 공유하는 Pydantic/domain 모델입니다. 공통 응답 envelope는 `tool_results.py`의 `ToolResult`를 사용합니다.
- `src/data_agent_backend/services/`: 정책, 승인, workspace 라우팅, artifact 저장/등록/계보, memory, catalog, datasource 등록/쿼리/profile, semantic registry, analysis context, run 이벤트/요약, SQL 실행, Python sandbox 실행, export, checkpoint 로직을 담습니다. `factory.py`의 `create_backend_services()`가 기본 서비스 그래프를 조립합니다.
- `src/data_agent_backend/services/connectors/`: datasource connector 계층입니다. 현재 지원 connector는 MySQL이며, 새 connector는 `DatasourceConnector` 프로토콜과 `DatasourceService`의 정책/검증 흐름을 따라야 합니다.
- `src/data_agent_backend/storage/`: SQLite 초기화/마이그레이션과 파일시스템 헬퍼입니다. DB 스키마 변경은 `migrations.py`에 누적하고 `SQLiteStore`의 마이그레이션 흐름을 깨지 않게 유지하세요.
- `src/data_agent_agent/`: DeepAgents 기반 CLI 분석 에이전트 계층입니다. `runner.py`는 `data-agent-agent` 콘솔 스크립트 대상이며 datasource 준비, run 생성, backend tool provider 선택, DeepAgents 실행을 오케스트레이션합니다. `tools.py`는 raw backend tool을 agent용 `get_catalog_summary`, `build_analysis_context`, `run_sql`, `run_python` 도구로 감쌉니다.
- `src/data_agent_agent/prompts/`: 에이전트 시스템 프롬프트 패키지입니다. SQL 원자료 조회와 Python 후처리/시각화/파일 생성을 구분하는 실행 규칙을 포함합니다.
- `docs/superpowers/`: 설계/구현 계획 문서입니다. 기능 설계나 큰 변경 계획을 남길 때 사용합니다.
- `tests/`: pytest 기반 백엔드, HTTP API, MCP 도구, datasource, run, workspace, artifact, sandbox, analysis context, agent layer 테스트입니다.

런타임 상태와 캐시는 커밋하지 마세요. 특히 `.data_agent/`, `.venv/`, `.uv-cache/`, `.pytest_cache/`, `.pytest_tmp_codex/`, `.worktrees/`, `.playwright-mcp/`, `__pycache__/`, 생성 artifact는 작업 산출물이 아닌 한 제외하세요.

## 빌드, 테스트, 개발 명령

의존성 설치와 명령 실행에는 `uv`를 사용합니다.

```powershell
uv sync --extra dev
```

런타임 의존성과 pytest/httpx를 포함한 개발 의존성을 설치합니다.

```powershell
uv run pytest -q
```

전체 테스트 스위트를 실행합니다.

```powershell
uv run data-agent-mcp
```

`data-agent-mcp` 콘솔 스크립트로 MCP 서버를 시작합니다.

```powershell
uv run data-agent-api
```

FastAPI HTTP API를 `127.0.0.1:8000`에서 시작합니다.

```powershell
uv run data-agent-agent --datasource-id <datasource_id> "분석 질문"
```

기존 datasource ID로 CLI 분석 에이전트를 실행합니다.

```powershell
uv run data-agent-agent "분석 질문"
```

`--datasource-id`를 생략하면 `.env`의 `DATA_AGENT_MYSQL_*` 값으로 MySQL datasource를 자동 준비합니다. 실행에는 `OPENAI_API_KEY`가 필요하며 모델은 `OPENAI_MODEL` 또는 `--model`로 지정할 수 있습니다. 기본 모델과 MCP stdio 실행 설정은 `src/data_agent_agent/config.py`를 따릅니다.

로컬 개발용 Python 실행을 켜려면 다음처럼 설정합니다.

```powershell
$env:DATA_AGENT_SANDBOX_BACKEND = "local"
uv run data-agent-agent "SQL 결과를 요약하고 차트 파일을 만들어줘"
```

`DATA_AGENT_LOCAL_PYTHON_EXECUTABLE`은 로컬 sandbox에서 사용할 Python 실행 파일 경로입니다. 비워 두면 현재 backend/agent 프로세스의 Python(`sys.executable`, 보통 `.venv`/`uv run` Python)을 사용합니다.

## 실행 흐름

일반적인 agent 실행 흐름은 다음과 같습니다.

1. `data-agent-agent`가 CLI 인자를 읽고 `OPENAI_API_KEY`, `OPENAI_MODEL`, `DATA_AGENT_MYSQL_*` 설정을 검증합니다.
2. `InProcessBackendToolProvider` 또는 MCP provider가 backend tool을 준비하고 필수 도구(`datasource_get_catalog_summary`, `analysis_build_context`, `datasource_query`, `sandbox_run_python`) 존재를 확인합니다.
3. datasource가 없으면 `.env`의 MySQL 설정으로 datasource를 생성/테스트/카탈로그 갱신합니다.
4. `RunService`가 run을 만들고 DeepAgents가 시스템 프롬프트와 agent tool을 사용해 분석을 수행합니다.
5. SQL 원자료 조회는 `run_sql` -> `datasource_query` -> `DatasourceService` 흐름으로 실행되고 결과는 artifact로 등록됩니다.
6. Python 후처리/통계/시각화/파일 생성은 `run_python` -> `sandbox_run_python` -> `SandboxExecutor` 흐름으로 실행됩니다.
7. 생성 파일과 실행 로그는 artifact로 등록되고 lineage는 입력 artifact와 연결됩니다.

HTTP/MCP 실행 경로도 가능한 한 같은 service 메서드와 `ToolResult` 계약을 공유해야 합니다.

## 런타임 저장소와 마운트

기본 `BackendConfig`는 `.data_agent/` 아래에 상태를 만듭니다.

- `.data_agent/backend.sqlite`: artifact 메타데이터와 preview/lineage, memory, approval, policy audit, export, run/event, datasource/catalog/profile/semantic 상태를 저장합니다.
- `.data_agent/workspace`: `/workspace` 마운트의 쓰기 가능한 로컬 파일 영역입니다.
- `.data_agent/artifacts`: `ArtifactStore`가 append-only artifact 콘텐츠를 저장하는 영역입니다.
- `.data_agent/catalog`: `/catalog` 읽기 전용 마운트입니다.
- `.data_agent/skills`: `/skills` 읽기 전용 마운트입니다.
- `.data_agent/exports`: `/exports` 읽기 전용 마운트입니다. export 생성은 승인된 `export.create` 흐름을 거쳐야 합니다.
- `.data_agent/secrets`: datasource 비밀번호 같은 내부 secret 저장 영역입니다. `/secrets`는 workspace mount로 노출하지 마세요.
- `.data_agent/sandbox`: Python sandbox 실행 디렉터리입니다. 실행별로 `runs/<execution_id>/code`, `inputs`, `workspace`, `outputs`, `logs` 하위 디렉터리를 사용합니다.

기본 라우터 마운트는 `/workspace`, `/artifacts`, `/catalog`, `/memory`, `/skills`, `/exports`입니다. `/secrets` 접근은 not-found처럼 숨기지 말고 정책 차단으로 처리되어야 합니다.

## 설정과 실행 제한

Python sandbox backend는 `DATA_AGENT_SANDBOX_BACKEND`로 선택합니다.

- `disabled`: 기본값입니다. `DisabledSandboxExecutor`를 사용하며 실제 Python 코드를 실행하지 않습니다.
- `local`: 로컬 개발용입니다. `LocalPythonSandboxExecutor`를 사용하며 승인 없이 `sandbox.python.run`을 허용합니다. 입력 artifact는 `DATA_AGENT_INPUTS_DIR`, 작업 디렉터리는 `DATA_AGENT_WORKSPACE_DIR`, 출력 파일은 `DATA_AGENT_OUTPUTS_DIR`로 전달합니다. subprocess 환경변수는 allowlist 기반으로 제한해 datasource/API secret을 넘기지 않아야 합니다.
- `docker`: Docker sandbox용입니다. `DockerSandboxExecutor`를 사용하며 `sandbox.python.run`은 승인 필요 흐름을 유지합니다. Docker 실행은 network none, read-only container, 제한된 tmpfs/resource 옵션을 유지해야 합니다.

레거시 `sandbox_enabled=True` 설정은 Docker backend 선택과 호환되어야 하지만, 새 코드는 `sandbox_backend`를 우선 사용하세요.

## 코딩 스타일 및 경계

4칸 들여쓰기를 사용하는 일반적인 Python 스타일을 따르고, 공개 인터페이스에는 타입 힌트를 작성하세요. 모듈명은 `policy_engine.py`, `tools_workspace.py`, `routes_workspace.py`처럼 소문자와 밑줄을 사용합니다. 클래스명은 `ArtifactRegistry`, `PolicyEngine`, `WorkspaceBackend`처럼 역할이 드러나게 작성합니다.

서비스 경계에서는 원시 딕셔너리보다 구조화된 모델을 우선하세요. 보안 및 정책 검사는 HTTP/MCP wrapper에만 두지 말고 서비스 계층에 유지하세요. MCP 도구와 HTTP API는 가능한 한 같은 서비스 메서드와 `ToolResult` 응답 계약을 공유해야 합니다.

새 기능을 추가할 때는 다음 경계를 지키세요.

- HTTP endpoint는 `src/data_agent_backend/api/routes_*.py`에 두고, 요청/응답 변환만 얇게 처리합니다.
- MCP tool은 `src/data_agent_backend/mcp/tools_*.py`에 두고, `services` 의존성 주입 패턴과 public tool wrapper 계약을 유지합니다.
- 비즈니스 로직, 정책 enforcement, persistence 변경은 `src/data_agent_backend/services/`와 `src/data_agent_backend/storage/`에 둡니다.
- 공통 응답은 성공과 실패 모두 `ToolResult` envelope를 유지합니다.
- agent 전용 orchestration은 `src/data_agent_agent/`에 두고, 백엔드 정책 우회 로직을 만들지 마세요.
- datasource secret은 `DatasourcePublic` 응답, artifact metadata, policy audit payload, Python subprocess 환경변수에 노출하지 마세요.
- Python 실행 결과 파일을 artifact로 등록할 때는 입력 artifact와 lineage를 연결하고, 실행 로그 artifact를 함께 남기세요.

## 정책, 승인, SQL 제한

`PolicyEngine`은 action 단위로 허용, 차단, 승인 필요 여부를 판단합니다. 기본 허용 범위에는 `catalog.read`, `workspace.list/read/write`, `artifact.preview/list/register`, `memory.propose/read`, `approval.read/resolve`, `policy.evaluate`, `datasource.create/read/test/catalog.refresh/profile`, `run.*`가 포함됩니다.

- `/artifacts` 직접 쓰기, `/catalog` 및 `/skills` 쓰기, `/secrets` 접근은 차단되어야 합니다.
- `/memory` 직접 쓰기와 `/exports` 직접 쓰기는 승인 필요 흐름으로 유지합니다.
- `sql.run`과 `datasource.query`는 읽기 전용 단일 SELECT 계열 쿼리만 허용하고, row limit이 `max_sql_row_limit_without_approval`을 넘으면 승인 필요 상태를 반환해야 합니다.
- `sandbox.python.run`은 `sandbox_backend=local`일 때만 승인 없이 허용합니다. `disabled`는 실제 실행 금지, `docker`는 승인 필요 흐름을 유지합니다.
- `export.create`는 승인 ID가 없으면 승인 필요 상태를 반환해야 합니다.
- `shell.run`, `network.call`, `package.install`은 현재 MVP 정책에서 차단 상태를 유지합니다.

SQL 실행은 두 흐름을 구분하세요.

- `SQLExecutor`의 `sql.run`은 로컬 DuckDB 쿼리로 취급합니다. DDL/DML, `PRAGMA`, `ATTACH`, `DETACH`, `INSTALL`, `LOAD`, `COPY`, `EXPORT`, `CALL`, 다중 문장을 보수적으로 차단합니다.
- `DatasourceService`의 `datasource.query`는 MySQL datasource를 대상으로 합니다. DDL/DML, `CALL`, `SET`, `LOCK`, `LOAD`, `OUTFILE`, `DUMPFILE`, `LOAD_FILE`, 권한 변경, 다중 문장 등 외부 영향이나 파일 접근 가능성이 있는 구문을 차단합니다.

## 테스트 지침

테스트는 pytest를 사용합니다. 테스트 파일은 `test_*.py`로 이름 짓고, 공통 fixture는 `tests/conftest.py`에 둡니다. 기존 `services(tmp_path)` fixture처럼 임시 디렉터리를 사용해 로컬 `.data_agent/` 내용에 의존하지 않게 하세요.

다음 영역이 바뀌면 관련 테스트를 추가하거나 갱신하세요.

- 정책 판단, 승인 요청/해결, policy audit persistence
- workspace mount 라우팅과 traversal/secret 차단
- artifact 저장, preview, lineage, workspace storage helper
- run 생성, 상태 전이, 이벤트, summary
- datasource 등록, secret 저장, catalog refresh/summary, MySQL query 검증, 결과 크기 제한, 장애 복구 details
- analysis context/profile/semantic registry, mart/metric/join path 조회와 갱신
- SQL 검증과 DuckDB result artifact 생성
- sandbox 비활성 계약, local Python 실행, Docker sandbox artifact 수집
- Python 실행의 입력 artifact 복사, 출력 파일 artifact 등록, 실행 로그, timeout, secret env 차단
- HTTP API의 `ToolResult` envelope와 validation error 형태
- MCP 도구의 `services` 인자 숨김 wrapper와 `ToolResult` 계약
- agent layer의 필수 backend 도구, datasource/run id 주입, `run_sql`/`run_python` wrapper, CLI 파서와 오류 메시지

선택적 통합 테스트가 외부 MySQL에 의존한다면 환경 변수가 없을 때 skip되도록 유지하세요. 현재 MySQL 통합 테스트는 `DATA_AGENT_TEST_MYSQL_URL`이 없으면 건너뛰어야 합니다.

## 커밋 및 풀 리퀘스트 지침

커밋 메시지는 `Add artifact export approval`, `Fix SQL policy validation`, `Document MCP server startup`처럼 간단한 명령형 문장으로 작성하세요.

풀 리퀘스트에는 간결한 요약, `uv run pytest -q` 같은 테스트 결과, 정책·승인·저장소 구조·HTTP API·MCP 도구 계약·agent orchestration에 영향을 주는 변경 사항을 포함하세요. 마이그레이션 또는 호환성 우려가 있으면 명시적으로 적으세요.
