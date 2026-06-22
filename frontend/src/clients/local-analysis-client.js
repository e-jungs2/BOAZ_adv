"use client";

import { normalizeAnalysisState, normalizeProgressEvent } from "../lib/normalizers";

const localArtifacts = [
  {
    id: "local-report-001",
    kind: "report",
    title: "월별 매출 하락 요약",
    preview: "전환율 하락과 신규 유입 감소가 핵심 원인으로 추정됩니다.",
    downloadUrl: null,
  },
  {
    id: "local-chart-001",
    kind: "chart",
    title: "월별 매출 추이",
    preview: "최근 4주 동안 매출과 세션 수가 함께 감소했습니다.",
    downloadUrl: null,
  },
];

const localEventPlan = [
  {
    stage: "request_received",
    title: "요청 수신",
    message: "사용자 분석 요청을 작업 thread로 등록했습니다.",
    status: "running",
  },
  {
    stage: "data_loading",
    title: "데이터 준비",
    message: "분석에 필요한 테이블과 기간 조건을 확인하고 있습니다.",
    status: "running",
  },
  {
    stage: "eda",
    title: "EDA 실행",
    message: "매출, 전환율, 유입 채널 지표의 변화를 비교하고 있습니다.",
    status: "running",
  },
  {
    stage: "insight",
    title: "인사이트 정리",
    message: "하락 원인 후보를 우선순위별로 정리했습니다.",
    status: "running",
  },
  {
    stage: "report",
    title: "보고서 작성",
    message: "분석 요약과 개선 제안을 artifact로 저장했습니다.",
    status: "completed",
    artifacts: localArtifacts,
  },
];

export function createLocalAnalysisClient() {
  return {
    async startAnalysis(payload) {
      const threadId = `local-thread-${Date.now()}`;

      return normalizeAnalysisState({
        threadId,
        runId: `local-run-${Date.now()}`,
        status: "running",
        title: payload.prompt?.slice(0, 40) || "로컬 분석 작업",
        artifacts: [],
      });
    },

    subscribeEvents(threadId, onEvent) {
      const timers = localEventPlan.map((event, index) =>
        window.setTimeout(() => {
          onEvent(
            normalizeProgressEvent({
              ...event,
              id: `${threadId}-event-${index + 1}`,
              threadId,
              createdAt: new Date().toISOString(),
            }),
          );
        }, 700 * (index + 1)),
      );

      return () => {
        timers.forEach((timer) => window.clearTimeout(timer));
      };
    },
  };
}
