import { backendJson } from "../../../../src/lib/backend-client";
import { normalizeArtifact } from "../../../../src/lib/normalizers";

export async function GET(_request, { params }) {
  const { artifactId } = await params;
  const raw = await backendJson(`/artifacts/${artifactId}`);
  return Response.json(normalizeArtifact(raw));
}
