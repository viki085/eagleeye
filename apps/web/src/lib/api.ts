const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ServiceHealth {
  name: string;
  status: "up" | "down";
  latency_ms: number | null;
  detail: string | null;
}

export interface HealthData {
  overall: "up" | "degraded";
  services: ServiceHealth[];
}

export interface ChatSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export type DocumentScope = "personal" | "enterprise";

export type DocumentStatus =
  | "UPLOADING"
  | "SCANNING"
  | "PARSING"
  | "CHUNKING"
  | "EMBEDDING"
  | "READY"
  | "FAILED";

export interface DocumentSummary {
  id: string;
  scope: DocumentScope;
  owner_id: string | null;
  uploaded_by: string;
  title: string;
  filename: string;
  mime: string;
  size_bytes: number;
  status: DocumentStatus;
  error: string | null;
  page_count: number | null;
  chunk_count: number | null;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  n: number;
  document_id: string;
  chunk_id: string;
  title: string;
  page: number | null;
  heading_path: string[];
  scope: DocumentScope;
  snippet: string;
}

export interface ChunkDetail {
  id: string;
  chunk_no: number;
  content: string;
  heading_path: string[];
  page: number | null;
  document: { id: string; title: string };
}

export interface Me {
  id: string;
  email: string;
  display_name: string | null;
  role: string;
}

export interface DailyUsage {
  day: string; // ISO date
  cost_usd: number;
  tokens: number;
}

export interface UsageSummary {
  limit_usd: number;
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
  runs: number;
  daily: DailyUsage[];
}

export interface MessagePart {
  type: string;
  text?: string;
  items?: unknown[];
  status?: string;
  route?: string | null;
  degraded?: boolean;
}

export interface ChatMessage {
  id: string;
  msg_no: number;
  role: "user" | "assistant";
  parts: { parts: MessagePart[] };
  run_id: string | null;
  created_at: string;
}

export interface ChatDetail {
  chat: ChatSummary;
  messages: ChatMessage[];
}

export interface Envelope<T> {
  success: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
}

export type TokenGetter = () => Promise<string | null>;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export class ApiClient {
  constructor(private readonly getToken: TokenGetter) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const token = await this.getToken();
    // FormData bodies must let the browser set the multipart boundary header.
    const isJson = typeof init?.body === "string";
    const resp = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.headers ?? {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(isJson ? { "Content-Type": "application/json" } : {}),
      },
      cache: "no-store",
    });
    let body: Envelope<T> | null = null;
    try {
      body = (await resp.json()) as Envelope<T>;
    } catch {
      // non-JSON error body; fall through
    }
    if (!resp.ok || body === null || !body.success || body.data === null) {
      const message = body?.error?.message ?? `API responded ${resp.status}`;
      throw new ApiError(message, resp.status);
    }
    return body.data;
  }

  fetchHealth(): Promise<HealthData> {
    return this.request<HealthData>("/v1/health");
  }

  listChats(): Promise<ChatSummary[]> {
    return this.request<ChatSummary[]>("/v1/chats");
  }

  createChat(): Promise<ChatSummary> {
    return this.request<ChatSummary>("/v1/chats", { method: "POST" });
  }

  getChat(chatId: string): Promise<ChatDetail> {
    return this.request<ChatDetail>(`/v1/chats/${chatId}`);
  }

  deleteChat(chatId: string): Promise<{ id: string }> {
    return this.request(`/v1/chats/${chatId}`, { method: "DELETE" });
  }

  sendMessage(
    chatId: string,
    text: string,
    idempotencyKey: string,
    docIds: readonly string[] = [],
  ): Promise<{ run_id: string }> {
    return this.request(`/v1/chats/${chatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ text, idempotency_key: idempotencyKey, doc_ids: docIds }),
    });
  }

  cancelRun(runId: string): Promise<{ run_id: string; cancelled: boolean }> {
    return this.request(`/v1/runs/${runId}/cancel`, { method: "POST" });
  }

  getUsage(): Promise<UsageSummary> {
    return this.request<UsageSummary>("/v1/me/usage");
  }

  getMe(): Promise<Me> {
    return this.request<Me>("/v1/me");
  }

  listDocuments(): Promise<DocumentSummary[]> {
    return this.request<DocumentSummary[]>("/v1/documents");
  }

  uploadDocument(file: File, scope: DocumentScope): Promise<DocumentSummary> {
    const form = new FormData();
    form.append("file", file);
    form.append("scope", scope);
    return this.request<DocumentSummary>("/v1/documents", { method: "POST", body: form });
  }

  deleteDocument(docId: string): Promise<{ id: string }> {
    return this.request(`/v1/documents/${docId}`, { method: "DELETE" });
  }

  getChunk(docId: string, chunkId: string): Promise<ChunkDetail> {
    return this.request<ChunkDetail>(`/v1/documents/${docId}/chunks/${chunkId}`);
  }

  async openRunStream(runId: string, signal?: AbortSignal): Promise<ReadableStream<Uint8Array>> {
    const token = await this.getToken();
    const resp = await fetch(`${API_URL}/v1/runs/${runId}/stream`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal,
    });
    if (!resp.ok || resp.body === null) {
      throw new ApiError(`Stream failed (${resp.status})`, resp.status);
    }
    return resp.body;
  }
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthData> {
  const resp = await fetch(`${API_URL}/v1/health`, { signal, cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`API responded ${resp.status}`);
  }
  const body: Envelope<HealthData> = await resp.json();
  if (!body.success || body.data === null) {
    throw new Error(body.error?.message ?? "Unknown API error");
  }
  return body.data;
}
