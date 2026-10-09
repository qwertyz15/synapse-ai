// Mirrors src/schema/schema.py and src/schema/task_data.py.

export type ToolCall = {
  name: string;
  args: Record<string, unknown>;
  id: string | null;
  type?: "tool_call";
};

export type ChatMessage = {
  type: "human" | "ai" | "tool" | "custom";
  content: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string | null;
  status?: "success" | "error" | null;
  run_id?: string | null;
  response_metadata?: Record<string, unknown>;
  custom_data?: Record<string, unknown>;
  attachments?: string[];
};

export type AgentInfo = { key: string; description: string };

export type ServiceMetadata = {
  agents: AgentInfo[];
  models: string[];
  default_agent: string;
  default_model: string;
};

export type ThreadInfo = {
  thread_id: string;
  agent_id: string;
  updated_at: string | null;
  title: string | null;
};

export type RagDocument = {
  doc_id: string;
  file_type: string;
  chunk_count: number;
  ingested_at: string;
  shared: boolean;
};

export type IngestionResult = {
  new: string[];
  updated: string[];
  deleted: string[];
  unchanged: string[];
  /** Accepted and waiting to be indexed in the background. */
  queued: string[];
  failed: Record<string, string>;
  rejected: Record<string, string>;
  chunks_written: number;
  full_rebuild: boolean;
};

export type TaskData = {
  name: string | null;
  run_id: string;
  state: "new" | "running" | "complete" | null;
  result: "success" | "error" | null;
  data: Record<string, unknown>;
};

export type StreamEvent =
  | { type: "token"; content: string }
  | { type: "message"; content: ChatMessage }
  | { type: "error"; content: string }
  | { type: "done" };

export type ChatAttachment = {
  name: string;
  file_type: string;
  chunk_count: number;
  ingested_at: string;
};

export type AttachmentResult = {
  attachments: ChatAttachment[];
  attached: string[];
  /** Accepted and waiting to be indexed in the background. */
  queued: string[];
  failed: Record<string, string>;
  rejected: Record<string, string>;
};

export type PlanInfo = {
  plan: "admin" | "unlimited" | "free";
  messages_today: number;
  /** null means no daily limit */
  daily_limit: number | null;
  /** null means every model */
  models: string[] | null;
  own_key_providers: string[];
  max_file_mb: number | null;
  library_files: number | null;
};

export type UserKey = { provider: string; last4: string; added_at: string; verified: boolean };

export type UserKeys = { enabled: boolean; providers: string[]; keys: UserKey[] };

export type AdminUser = {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  plan: "admin" | "unlimited" | "free";
  daily_message_limit: number | null;
  effective_limit: number | null;
  messages_today: number;
  own_key_providers: string[];
  blocked: boolean;
  created_at: string;
  last_login_at: string;
};

export type AdminUserUpdate = {
  plan?: "free" | "unlimited";
  daily_message_limit?: number | null;
  blocked?: boolean;
};

export type UploadJob = {
  id: string;
  name: string;
  kind: "library" | "attachment";
  thread_id: string | null;
  status: "queued" | "indexing" | "ready" | "failed";
  error: string | null;
  created_at: string;
  updated_at: string;
};
