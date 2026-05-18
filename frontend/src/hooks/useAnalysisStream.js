"use client";

import { useEffect, useState } from "react";
import { analysisClient } from "../clients/analysis-client";

export function useAnalysisStream(threadId, onStatePatch) {
  const [events, setEvents] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);

  useEffect(() => {
    if (!threadId) return;

    setEvents([]);
    setIsStreaming(true);

    const unsubscribe = analysisClient.subscribeEvents(
      threadId,
      (event) => {
        setEvents((current) => [...current, event]);

        if (event.status) {
          onStatePatch((current) => ({
            ...current,
            status: event.status,
            artifacts: event.artifacts ?? current?.artifacts ?? [],
          }));
        }

        if (event.status === "completed" || event.status === "failed") {
          setIsStreaming(false);
        }
      },
      () => {
        setIsStreaming(false);
      },
    );

    return () => {
      setIsStreaming(false);
      unsubscribe();
    };
  }, [threadId, onStatePatch]);

  return { events, isStreaming };
}
