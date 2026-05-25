# Data Agent 백엔드/MCP 기반

이 패키지는 LangGraph 기반 데이터 분석 에이전트 프레임워크의 백엔드 계약 계층입니다. 최종 분석 그래프, 플래너, 라우터, 프로파일러, 보고서 작성기, Python 실행 흐름은 의도적으로 구현하지 않습니다.

## 아키텍처

백엔드는 인터페이스 중심으로 구성됩니다.

- `WorkspaceBackend`는 LLM이 바라보는 가상 파일시스템 facade입니다.
- `WorkspaceRouter`는 논리 마운트를 목적별 마운트 백엔드로 위임합니다.
- `ArtifactRegistry`는 아티팩트 메타데이터, 미리보기, 계보, 권한, 증거 링크를 SQLite에 저장합니다.
- `ArtifactStore`는 append-only 아티팩트 콘텐츠를 로컬 파일시스템에 저장합니다.
- `MemoryStore`는 승인된 재사용 지식을 아티팩트와 분리해 저장합니다.
- `PolicyEngine`은 서비스 계층 정책을 적용하고 차단 또는 승인 필요 결정을 감사합니다.
- `ApprovalStore`는 승인 요청과 처리 이벤트를 영속화합니다.
- `SQLExecutor`는 보수적인 읽기 전용 DuckDB 쿼리를 실행하고 쿼리/결과 아티팩트를 등록합니다.
- `SandboxExecutor`는 인터페이스이며, MVP는 `DisabledSandboxExecutor`를 사용합니다.

## 논리 경로

에이전트는 다음 마운트를 봅니다.

- `/workspace`: 초안, 노트, SQL, 임시 파일을 읽고 씁니다.
- `/artifacts`: 읽기 전용 아티팩트 뷰입니다. 직접 쓰기는 차단됩니다.
- `/catalog`: 테이블 스키마, 용어집, 데이터셋 메타데이터의 읽기 전용 뷰입니다.
- `/memory`: 활성 메모리의 읽기 전용 뷰입니다. 쓰기는 메모리 도구를 통한 승인이 필요합니다.
- `/skills`: MVP용 분석 플레이북의 읽기 전용 뷰입니다.
- `/exports`: 통제된 내보내기 뷰입니다. 내보내기는 `export_create`를 통한 승인이 필요합니다.

`/secrets`는 절대 마운트되거나 목록에 표시되지 않습니다. 접근 시도는 조용한 not-found가 아니라 보안 차단으로 반환됩니다.

## 저장소 레이아웃

런타임 상태는 기본적으로 `.data_agent/`에 저장됩니다.

- `.data_agent/backend.sqlite`: 메타데이터, 계보, 메모리, 승인, 정책 감사 로그입니다.
- `.data_agent/workspace`: 워크스페이스 초안 파일입니다.
- `.data_agent/artifacts`: 아티팩트 ID별 append-only 아티팩트 콘텐츠입니다.
- `.data_agent/catalog`: 읽기 전용 카탈로그 파일입니다.
- `.data_agent/skills`: 읽기 전용 스킬 파일입니다.
- `.data_agent/exports`: 통제된 내보내기 파일입니다.

대용량 아티팩트 콘텐츠는 SQLite에 저장하지 않습니다.

## 정책 및 승인

정책 판단은 `workspace.write`, `sql.run`, `sandbox.python.run`, `export.create`처럼 점으로 구분된 작업명을 사용합니다.

- `policy_blocked`: 승인 여부와 관계없이 절대 실행하면 안 되는 작업입니다. 예: secret 접근, DDL/DML SQL, 여러 SQL 문장, `/artifacts` 직접 쓰기, shell/network/package install.
- `approval_required`: 승인되기 전까지 실행하지 않는 작업입니다. 승인 처리는 결정만 기록하며, 호출자는 원래 도구를 `approval_id`가 포함된 context로 다시 호출해야 합니다.

차단 및 승인 필요 결정은 `policy_audit_logs`에 영속화됩니다.

## 샌드박스

이 MVP에서는 Python 실행이 비활성화되어 있습니다. `sandbox_run_python`은 계약 안정화를 위해 존재하지만 코드를 실행하지 않으며, 호스트 `exec`, `eval`, subprocess, shell, Docker, pip, network API를 호출하지 않습니다. 향후 provider는 같은 `SandboxExecutor.run_python(...)` 인터페이스를 구현할 수 있습니다.

## SQL 정책

SQL은 로컬 분석 쿼리에 DuckDB를 사용합니다. 검증은 `sqlglot`과 보수적인 키워드 검사를 함께 사용합니다.

허용:

- 단일 읽기 전용 SELECT 스타일 쿼리입니다.

차단:

- DDL/DML, `PRAGMA`, `ATTACH`, `DETACH`, `INSTALL`, `LOAD`, `COPY`, 여러 문장, 외부 쓰기 지향 작업입니다.

행 수는 항상 쿼리를 `LIMIT`으로 감싸 제한합니다.

## MCP 서버

서버 실행:

```powershell
uv run data-agent-mcp
```

모든 MCP 도구는 다음 형태를 반환합니다.

```json
{
  "ok": true,
  "data": {},
  "error": null
}
```

또는:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "POLICY_BLOCKED",
    "message": "Direct write to /artifacts is not allowed.",
    "details": {}
  }
}
```

## 테스트

의존성을 설치하고 테스트를 실행합니다.

```powershell
uv sync --extra dev
uv run pytest -q
```

## 범위 제외

이 MVP는 LangGraph 분석 노드, 플래너/라우터/프로파일러/보고서 그래프, 최종 답변 생성, 고급 UI, 벡터 메모리, 다중 사용자 인증, 프로덕션 RBAC, 전체 checkpoint 재생/time travel, Docker 샌드박싱, 실제 Python 코드 실행, shell 실행, 패키지 설치, network 격리, 원격 샌드박스 provider, 자동 승인 실행, 보수적인 MVP 검증기를 넘어서는 프로덕션 수준 SQL 샌드박싱을 의도적으로 제외합니다.
