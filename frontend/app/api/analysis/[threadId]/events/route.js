import { backendFetch } from "../../../../../src/lib/backend-client";
import { normalizeSseStream } from "../../../../../src/lib/sse-stream";

export async function GET(_request, { params }) {
  const { threadId } = await params;
  const response = await backendFetch(`/analysis/${threadId}/events`, {
    headers: { Accept: "text/event-stream" },
  });

  return new Response(normalizeSseStream(response.body), {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
