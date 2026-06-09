# Repository Guidelines

## 작업 범위 제한

이 작업공간에서는 `data_agent_backend` 디렉터리 내부 파일만 읽고, 실행하고, 수정한다.

- `data_agent_backend` 이외의 상위/외부 디렉터리 참조를 금지한다.
- `..` 경로를 사용해 상위 폴더로 이동하거나 파일을 읽는 행위를 금지한다.
- `DATA_Analyst_Assistant_Agent/`, `eda_agent/`, `sql_agent/`, 상위 `tests/`, 상위 `docs/`, 상위 `.env.example` 등 외부 폴더와 파일을 읽거나 수정하지 않는다.
- 테스트, 검색, 상태 확인, Git diff 확인도 현재 `data_agent_backend` 폴더 내부로만 제한한다.
- 외부 레이어가 필요해 보이는 경우에도 직접 접근하지 말고 사용자에게 먼저 요청한다.

## Project Structure & Module Organization

이 디렉터리는 `data_agent_backend` Python 패키지입니다. `api/`는 FastAPI 앱과 라우터(`routes_*.py`)를 담고, `mcp/`는 MCP 서버와 도구 등록 코드를 관리합니다. `models/`에는 Pydantic 데이터 모델이 있으며, `services/`에는 실행, 저장소, 정책, 워크스페이스 등 비즈니스 로직이 있습니다. `storage/`는 SQLite 및 파일시스템 저장 구현을 담당합니다. 커넥터별 구현은 `services/connectors/`에 둡니다.

## Build, Test, and Development Commands

패키지 상위 디렉터리에서 실행하는 것을 기준으로 합니다.

```powershell
python -m uvicorn data_agent_backend.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

HTTP API를 로컬에서 실행합니다. `/health`로 상태를 확인합니다.

```powershell
python -m data_agent_backend.mcp.server
```

MCP 서버를 실행합니다. `mcp` 패키지가 설치되어 있어야 합니다.

```powershell
python -m pytest
```

테스트 전체를 실행합니다. 현재 이 하위 디렉터리에는 `tests/`가 없으므로, 새 기능에는 테스트를 함께 추가하세요.

## Coding Style & Naming Conventions

Python 3.11+ 문법과 타입 힌트를 사용합니다. 파일 상단에는 기존 코드처럼 `from __future__ import annotations`를 유지합니다. 들여쓰기는 4칸 공백을 사용하고, 함수와 변수는 `snake_case`, 클래스는 `PascalCase`로 작성합니다. API 라우터 파일은 `routes_<domain>.py`, MCP 도구 파일은 `tools_<domain>.py` 패턴을 따릅니다. 요청/응답 데이터는 가능하면 Pydantic 모델로 표현하고, 공통 결과 형식은 `ToolResult`를 사용합니다.

## Testing Guidelines

테스트는 `pytest` 기준으로 작성합니다. 새 테스트 파일은 `tests/test_<module>.py` 이름을 사용하고, 서비스 단위 테스트는 외부 네트워크나 실제 샌드박스 실행에 의존하지 않도록 임시 디렉터리와 목 객체를 사용하세요. FastAPI 라우터 변경 시에는 성공 응답뿐 아니라 검증 오류와 실패 응답 형태도 확인합니다.

## Commit & Pull Request Guidelines

최근 커밋은 `Add ...`, `Fix ...`, `Revert ...`처럼 짧은 명령형 영어 제목을 사용합니다. 같은 스타일을 유지하고, 한 커밋에는 하나의 논리적 변경만 담습니다. PR에는 변경 목적, 주요 수정 파일, 테스트 결과를 포함하세요. API 동작이나 응답 스키마가 바뀌면 예시 요청/응답 또는 마이그레이션 주의사항을 적습니다.

## Security & Configuration Tips

기본 설정은 `config.py`의 `BackendConfig`에 있습니다. 샌드박스, 네트워크, 패키지 설치 정책은 보안에 직접 영향을 주므로 기본값을 바꿀 때 PR 설명에 이유를 남기세요. 생성 데이터는 기본적으로 `.data_agent/` 아래에 저장되며, 민감한 실행 결과나 로컬 DB 파일은 커밋하지 않습니다.
