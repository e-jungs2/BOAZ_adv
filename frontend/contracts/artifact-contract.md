# Artifact Contract

분석 에이전트가 만든 결과물의 UI 표현 계약입니다.

```json
{
  "id": "artifact_123",
  "kind": "report | chart | table | sql | file",
  "title": "월별 매출 하락 원인 분석",
  "preview": "주요 하락 원인은 신규 유입 감소와 전환율 하락입니다.",
  "downloadUrl": "/api/artifacts/artifact_123/download"
}
```

## UI 렌더링 기준

- `report`: Markdown/HTML 보고서 영역
- `chart`: 차트 미리보기 또는 이미지
- `table`: 데이터 테이블
- `sql`: SQL 코드 블록
- `file`: 다운로드 링크
