"use client";

import { useState } from "react";
import { AnalysisRequestForm } from "../src/components/AnalysisRequestForm";
import { ArtifactPanel } from "../src/components/ArtifactPanel";
import { ProgressTimeline } from "../src/components/ProgressTimeline";
import { StatusBadge } from "../src/components/StatusBadge";
import { analysisClient } from "../src/clients/analysis-client";
import { useAnalysisStream } from "../src/hooks/useAnalysisStream";

export default function HomePage() {
  const [threadId, setThreadId] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const { events, isStreaming } = useAnalysisStream(threadId, setAnalysis);

  async function startAnalysis(payload) {
    const data = await analysisClient.startAnalysis(payload);
    setThreadId(data.threadId);
    setAnalysis(data);
  }

  return (
    <main className="shell">
      <aside className="sidebar stack">
        <div>
          <h1 className="title">Data Analysis Agent</h1>
          <p className="muted">
            UI는 analysisClient만 바라보고, local/http 구현은 내부에서
            교체됩니다.
          </p>
        </div>
        <AnalysisRequestForm onSubmit={startAnalysis} />
      </aside>

      <section className="workspace">
        <div className="panel stack">
          <div className="row">
            <h2 className="section-title">진행 상황</h2>
            <StatusBadge status={analysis?.status} isStreaming={isStreaming} />
          </div>
          <ProgressTimeline events={events} />
        </div>

        <div className="panel stack">
          <div>
            <h2 className="section-title">산출물</h2>
            <p className="muted">
              보고서, 차트, SQL, EDA 결과 같은 artifact가 여기에 렌더링됩니다.
            </p>
          </div>
          <ArtifactPanel artifacts={analysis?.artifacts ?? []} />
        </div>
      </section>
    </main>
  );
}
