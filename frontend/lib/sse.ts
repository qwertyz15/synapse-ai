import type { StreamEvent } from "./types";

function parseEvent(raw: string): StreamEvent | null {
  const data = raw
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).replace(/^ /, ""))
    .join("\n");
  if (!data) return null;
  if (data === "[DONE]") return { type: "done" };
  try {
    const parsed = JSON.parse(data);
    if (parsed?.type === "token" || parsed?.type === "message" || parsed?.type === "error") {
      return parsed as StreamEvent;
    }
  } catch {}
  return null;
}

export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split(/\r?\n\r?\n/);
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const event = parseEvent(part);
        if (!event) continue;
        yield event;
        if (event.type === "done") return;
      }
    }
    const tail = parseEvent(buffer);
    if (tail) yield tail;
  } finally {
    reader.releaseLock();
  }
}
