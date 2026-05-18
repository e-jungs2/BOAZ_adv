# Progress Event Contract

SSE로 UI에 전달되는 진행 이벤트입니다.

```json
{
  "id": "event_123",
  "threadId": "thread_123",
  "runId": "run_456",
  "stage": "eda",
  "title": "EDA 실행",
  "message": "결측치와 이상치를 확인하는 중입니다.",
  "status": "running",
  "artifacts": [],
  "createdAt": "2026-05-18T10:00:00.000Z"
}
```

## 이벤트 예시

- `request_received`: 사용자 요청 수신
- `data_loading`: 데이터셋 또는 DB 결과 로딩
- `sql_generation`: SQL 생성
- `eda`: 탐색적 분석
- `visualization`: 차트 생성
- `insight`: 인사이트 도출
- `report`: 보고서 작성
- `waiting`: 사용자 입력 또는 승인 대기
- `completed`: 작업 완료
- `failed`: 작업 실패
