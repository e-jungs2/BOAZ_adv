# Frontend

데이터 분석 에이전트 서비스를 위한 **UI + UI용 API 가공 계층** 스켈레톤입니다.

이 폴더는 실제 LangGraph/백엔드를 구현하지 않습니다. 기본적으로 이미 존재하는
백엔드를 `BACKEND_BASE_URL` 뒤에 두고, 프론트엔드가 쓰기 좋은 계약으로 변환하는
BFF(Backend for Frontend) 역할을 합니다.

빠른 UI 개발을 위해 `local` 모드도 제공합니다. 이 모드에서는 실제 백엔드 없이
브라우저 안에서 모의 분석 상태와 진행 이벤트를 생성합니다.

## 역할

- UI는 `analysisClient`만 호출합니다.
- `http` 모드에서는 `analysisClient`가 이 프로젝트의 `/api/*`를 호출합니다.
- `local` 모드에서는 `analysisClient`가 브라우저 안에서 모의 데이터를 생성합니다.
- `/api/*`는 실제 백엔드 응답을 UI용 형태로 정규화합니다.
- SSE 진행 이벤트를 UI로 전달합니다.
- thread/run/artifact 같은 백엔드 개념을 UI가 다루기 쉬운 형태로 감쌉니다.

## 실행 위치

```text
Browser UI
  -> analysisClient
    -> local mode: mock analysis events in browser
    -> http mode: /api/* in this project
      -> existing backend at BACKEND_BASE_URL
        -> LangGraph / runtime / storage
```

## 기본 실행

```bash
npm install
npm run dev
```

`.env.local` 예시:

```bash
BACKEND_BASE_URL=http://localhost:8000
NEXT_PUBLIC_ANALYSIS_CLIENT_MODE=http
```

백엔드 없이 UI 흐름만 빠르게 확인하려면:

```bash
NEXT_PUBLIC_ANALYSIS_CLIENT_MODE=local
```

## 핵심 폴더

```text
app/
  page.jsx                  # 데이터 분석 에이전트 UI 첫 화면
  api/                      # UI 전용 API adapter

src/
  clients/                  # local/http 교체 가능한 UI client
  components/               # 화면 구성 컴포넌트
  hooks/                    # SSE/EventSource 등 UI 상태 훅
  lib/                      # backend fetch, normalizer

contracts/                  # UI와 API 계층 사이의 계약 문서
```

## 설계 원칙

백엔드 응답 구조가 바뀌어도 UI 전체가 흔들리지 않도록, UI는
`src/clients/analysis-client.js`만 바라봅니다. `local`에서 `http`로 넘어갈 때도
UI 컴포넌트는 가능한 한 유지하고, 교체 범위는 client/API/normalizer에 둡니다.
