import { backendFetch } from "../../../../../src/lib/backend-client";

export async function GET(_request, { params }) {
  const { artifactId } = await params;
  const response = await backendFetch(`/artifacts/${artifactId}/download`, {
    headers: { Accept: "*/*" },
  });

  return new Response(response.body, {
    headers: {
      "Content-Type":
        response.headers.get("Content-Type") ?? "application/octet-stream",
      "Content-Disposition":
        response.headers.get("Content-Disposition") ?? "attachment",
    },
  });
}
