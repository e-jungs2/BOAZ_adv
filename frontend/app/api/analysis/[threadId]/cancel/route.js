import { backendJson } from "../../../../../src/lib/backend-client";
import { normalizeAnalysisState } from "../../../../../src/lib/normalizers";

export async function POST(_request, { params }) {
  const { threadId } = await params;
  const raw = await backendJson(`/analysis/${threadId}/cancel`, {
    method: "POST",
  });

  return Response.json(normalizeAnalysisState(raw));
}
