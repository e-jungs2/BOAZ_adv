"use client";

export function createHttpAnalysisClient() {
  return {
    async startAnalysis(payload) {
      const response = await fetch("/api/analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error("분석 요청을 시작하지 못했습니다.");
      }

      return response.json();
    },

    subscribeEvents(threadId, onEvent, onError) {
      const source = new EventSource(`/api/analysis/${threadId}/events`);

      source.onmessage = (message) => {
        if (message.data === "[DONE]") {
          source.close();
          return;
        }

        onEvent(JSON.parse(message.data));
      };

      source.onerror = (error) => {
        source.close();
        onError?.(error);
      };

      return () => source.close();
    },
  };
}
