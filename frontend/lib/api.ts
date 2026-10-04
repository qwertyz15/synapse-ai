import { readEvents } from "./sse";
import type { ChatMessage, IngestionResult, RagDocument, ServiceMetadata, StreamEvent, ThreadInfo } from "./types";

const BASE = "/api/agent";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {}
    throw new ApiError(detail || `Request failed (${res.status})`, res.status);
  }
  return res.json();
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getInfo = () => request<ServiceMetadata>("info");

export const getHistory = (agent: string, threadId: string) =>
  request<{ messages: ChatMessage[] }>(`${agent}/history`, json({ thread_id: threadId })).then((r) => r.messages);

export const getThreads = (agent: string, limit = 30) =>
  request<{ threads: ThreadInfo[] }>(`${agent}/threads?limit=${limit}`).then((r) => r.threads);

export async function getAllThreads(agents: string[]): Promise<ThreadInfo[]> {
  const results = await Promise.allSettled(agents.map((a) => getThreads(a)));
  return results
    .flatMap((r) => (r.status === "fulfilled" ? r.value : []))
    .sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
}

export const sendFeedback = (runId: string, score: number) =>
  request("feedback", json({ run_id: runId, key: "human-feedback-thumbs", score }));

export const listDocuments = () => request<{ documents: RagDocument[] }>("rag/documents").then((r) => r.documents);

export function uploadDocuments(files: File[]) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return request<IngestionResult>("rag/documents", { method: "POST", body: form });
}

export const deleteDocument = (docId: string) =>
  request<IngestionResult>(`rag/documents/${docId.split("/").map(encodeURIComponent).join("/")}`, {
    method: "DELETE",
  });

export async function* streamChat(
  agent: string,
  body: { message: string; thread_id: string; model?: string },
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${BASE}/${agent}/stream`, {
    ...json({ ...body, stream_tokens: true }),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = `Request failed (${res.status})`;
    try {
      const b = await res.json();
      if (b.detail) detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {}
    throw new ApiError(detail, res.status);
  }
  yield* readEvents(res.body);
}

export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
    (+c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (+c / 4)))).toString(16),
  );
}
