import { readEvents } from "./sse";
import type {
  AttachmentResult,
  ChatAttachment,
  ChatMessage,
  IngestionResult,
  RagDocument,
  ServiceMetadata,
  StreamEvent,
  ThreadInfo,
} from "./types";

const BASE = "/api/agent";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  let code: string | undefined;
  try {
    const body = await res.json();
    detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    code = typeof body.code === "string" ? body.code : undefined;
  } catch {}
  return new ApiError(detail || `Request failed (${res.status})`, res.status, code);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/${path}`, init);
  if (!res.ok) throw await toApiError(res);
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

export const deleteThread = (agent: string, threadId: string) =>
  request<{ thread_id: string; attachments_removed: number }>(`${agent}/threads/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
  });

/** Every chat of this browser's user across agents, newest first; hidden agents are filtered out. */
export async function getAllThreads(agents: string[], limit = 100): Promise<ThreadInfo[]> {
  const visible = new Set(agents);
  const { threads } = await request<{ threads: ThreadInfo[] }>(`chats?limit=${limit}`);
  return threads.filter((t) => visible.has(t.agent_id));
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

const threadQuery = (threadId: string) => `thread_id=${encodeURIComponent(threadId)}`;

export const listAttachments = (threadId: string) =>
  request<{ attachments: ChatAttachment[] }>(`rag/attachments?${threadQuery(threadId)}`).then((r) => r.attachments);

export function attachToChat(threadId: string, files: File[]) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return request<AttachmentResult>(`rag/attachments?${threadQuery(threadId)}`, { method: "POST", body: form });
}

export const detachFromChat = (threadId: string, name: string) =>
  request<{ attachments: ChatAttachment[] }>(`rag/attachments/${encodeURIComponent(name)}?${threadQuery(threadId)}`, {
    method: "DELETE",
  }).then((r) => r.attachments);

export async function* streamChat(
  agent: string,
  body: {
    message: string;
    thread_id: string;
    model?: string;
    connectors?: string[];
    github_write?: boolean;
    attachments?: string[];
  },
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${BASE}/${agent}/stream`, {
    ...json({ ...body, stream_tokens: true }),
    signal,
  });
  if (!res.ok || !res.body) throw await toApiError(res);
  yield* readEvents(res.body);
}

export type GithubStatus = {
  configured: boolean;
  connected: boolean;
  login: string | null;
  avatar_url: string | null;
  installed?: boolean | null;
  manage_url?: string;
};

export async function getGithubStatus(): Promise<GithubStatus> {
  const res = await fetch("/api/github/status", { cache: "no-store" });
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export async function disconnectGithub(): Promise<void> {
  const res = await fetch("/api/github/disconnect", { method: "POST" });
  if (!res.ok) throw await toApiError(res);
}

export const githubLoginUrl = (returnTo: string) => `/api/github/login?returnTo=${encodeURIComponent(returnTo)}`;
export const githubInstallUrl = (returnTo: string) => `/api/github/install?returnTo=${encodeURIComponent(returnTo)}`;

export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
    (+c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (+c / 4)))).toString(16),
  );
}
