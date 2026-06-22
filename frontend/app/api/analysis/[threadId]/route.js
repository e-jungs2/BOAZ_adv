import { backendJson } from "../../../../src/lib/backend-client";
import { normalizeAnalysisState } from "../../../../src/lib/normalizers";

export async function GET(_request, { params }) {
  const { threadId } = await params;
  const raw = await backendJson(`/analysis/${threadId}`);
  return Response.json(normalizeAnalysisState(raw));
}
