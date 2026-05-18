export function normalizeAnalysisState(raw = {}) {
  return {
    threadId: raw.thread_id ?? raw.threadId ?? raw.id,
    runId: raw.run_id ?? raw.runId ?? null,
    status: raw.status ?? "queued",
    title: raw.title ?? "데이터 분석 작업",
    artifacts: (raw.artifacts ?? []).map(normalizeArtifact),
    nextAction: raw.next_action ?? raw.nextAction ?? null,
  };
}

export function normalizeProgressEvent(raw = {}) {
  return {
    id: raw.id ?? `${Date.now()}-${Math.random()}`,
    threadId: raw.thread_id ?? raw.threadId ?? null,
    runId: raw.run_id ?? raw.runId ?? null,
    stage: raw.stage ?? raw.node ?? "unknown",
    title: raw.title ?? raw.event ?? "진행 이벤트",
    message: raw.message ?? raw.content ?? "",
    status: raw.status ?? null,
    artifacts: raw.artifacts ? raw.artifacts.map(normalizeArtifact) : undefined,
    createdAt: raw.created_at ?? raw.createdAt ?? new Date().toISOString(),
  };
}

export function normalizeArtifact(raw = {}) {
  const id = raw.id ?? raw.artifact_id ?? raw.path;

  return {
    id,
    kind: raw.kind ?? raw.type ?? "document",
    title: raw.title ?? raw.name ?? id,
    preview: raw.preview ?? raw.summary ?? "",
    downloadUrl:
      raw.downloadUrl !== undefined
        ? raw.downloadUrl
        : id
          ? `/api/artifacts/${encodeURIComponent(id)}/download`
          : null,
  };
}
