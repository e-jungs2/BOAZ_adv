import { backendJson } from "../../../../../src/lib/backend-client";
import { normalizeAnalysisState } from "../../../../../src/lib/normalizers";

export async function POST(request, { params }) {
  const { threadId } = await params;
  const payload = await request.json();

  const raw = await backendJson(`/analysis/${threadId}/approve`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  return Response.json(normalizeAnalysisState(raw));
}
