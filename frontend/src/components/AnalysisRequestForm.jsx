"use client";

import { useState } from "react";

export function AnalysisRequestForm({ onSubmit }) {
  const [prompt, setPrompt] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const canSubmit = prompt.trim().length > 0 && !isSubmitting;

  async function handleSubmit(event) {
    event.preventDefault();
    if (!canSubmit) return;

    setIsSubmitting(true);
    try {
      await onSubmit({
        prompt,
        datasetScope: "default",
        outputPreferences: ["summary", "chart", "sql"],
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="stack" onSubmit={handleSubmit}>
      <textarea
        className="input"
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        placeholder="예: 지난달 매출 하락 원인을 분석하고 주요 지표와 개선 제안을 정리해줘."
      />
      <button className="button" disabled={!canSubmit} type="submit">
        분석 시작
      </button>
    </form>
  );
}
