import { normalizeProgressEvent } from "./normalizers";

export function normalizeSseStream(readable) {
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let buffer = "";

  return readable.pipeThrough(
    new TransformStream({
      transform(chunk, controller) {
        buffer += decoder.decode(chunk, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          const dataLine = frame
            .split("\n")
            .find((line) => line.startsWith("data:"));

          if (!dataLine) continue;

          const rawData = dataLine.replace(/^data:\s*/, "");
          if (rawData === "[DONE]") {
            controller.enqueue(encoder.encode("data: [DONE]\n\n"));
            continue;
          }

          try {
            const normalized = normalizeProgressEvent(JSON.parse(rawData));
            controller.enqueue(
              encoder.encode(`data: ${JSON.stringify(normalized)}\n\n`),
            );
          } catch {
            controller.enqueue(encoder.encode(`${frame}\n\n`));
          }
        }
      },
      flush(controller) {
        if (buffer.trim().length > 0) {
          controller.enqueue(encoder.encode(`${buffer}\n\n`));
        }
      },
    }),
  );
}
