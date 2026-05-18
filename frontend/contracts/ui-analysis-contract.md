# UI Analysis Contract

UI가 기대하는 분석 작업 상태입니다. 실제 백엔드 응답은 이 형태로 정규화됩니다.

```json
{
  "threadId": "thread_123",
  "runId": "run_456",
  "status": "queued | running | waiting | completed | failed",
  "title": "데이터 분석 작업",
  "artifacts": [],
  "nextAction": null
}
```

## 책임

- `threadId`: UI가 이후 이벤트 스트림, 후속 입력, 취소 요청에 사용하는 기준 ID
- `runId`: 특정 실행 단위가 필요할 때 사용하는 ID
- `status`: UI의 뱃지, 버튼 상태, 입력 가능 여부를 결정
- `artifacts`: 보고서, 차트, SQL, 테이블 등 결과물 목록
- `nextAction`: 사용자 승인, 추가 질문, 파일 선택 등 interrupt/resume에 필요한 UI 힌트
