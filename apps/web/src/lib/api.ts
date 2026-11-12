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

export interface MessagePart {
  type: string;
  text?: string;
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
    const resp = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.headers ?? {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
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

  sendMessage(chatId: string, text: string, idempotencyKey: string): Promise<{ run_id: string }> {
    return this.request(`/v1/chats/${chatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ text, idempotency_key: idempotencyKey }),
    });
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
