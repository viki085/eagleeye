import type { DemoVisit } from "./demo-visit";

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
  /** May add/delete enterprise documents (the API enforces this regardless of the UI). */
  can_manage_enterprise: boolean;
  /** The shared public demo account: demo banner, suggested questions, no account settings. */
  is_demo?: boolean;
}

export interface ArtifactColumn {
  name: string;
  type: string;
}

/** A query result shown under an answer (live `artifact` event or persisted part). */
export interface ArtifactView {
  artifact_id: string;
  type: string;
  title: string;
  sql: string;
  source: string;
  columns: ArtifactColumn[];
  row_count: number;
  truncated: boolean;
  preview: unknown[][];
  assumptions: string;
  /** Code shown in the card: warehouse SQL, DuckDB SQL or Python (older parts: absent = sql). */
  mode?: "sql" | "duckdb" | "python";
}

/** A chart under an answer: Vega-Lite spec built server-side from the data (no colours). */
export interface ChartView {
  chart_id: string;
  title: string;
  spec: Record<string, unknown>;
  summary: string;
  source_id: string;
}

export type DatasetStatus = "UPLOADED" | "PROFILING" | "READY" | "FAILED";

export interface DatasetSummary {
  id: string;
  title: string;
  filename: string;
  sheet: string;
  origin: string;
  status: DatasetStatus;
  error: string | null;
  row_count: number;
  column_count: number;
  columns: ArtifactColumn[];
  size_bytes: number;
  summary: string;
  created_at: string | null;
}

export interface ProfileTopValue {
  value: unknown;
  count: number;
}

export interface ProfileColumn {
  name: string;
  original: string;
  type: string;
  kind: "numeric" | "temporal" | "boolean" | "text";
  null_pct: number;
  distinct: number;
  min?: unknown;
  max?: unknown;
  mean?: number | null;
  median?: number | null;
  std?: number | null;
  outliers?: number;
  top?: ProfileTopValue[];
  flags: string[];
}

export interface DatasetProfile {
  row_count: number;
  column_count: number;
  duplicate_rows: number;
  columns: ProfileColumn[];
  correlations: { a: string; b: string; r: number }[];
  warnings: string[];
  sample: { columns: string[]; rows: unknown[][] };
}

export interface DatasetDetail extends DatasetSummary {
  profile: Partial<DatasetProfile>;
  column_map: Record<string, string>;
}

/** File extensions routed to the data-file pipeline instead of document ingestion. */
export const DATA_FILE_EXTENSIONS = [".csv", ".tsv", ".xlsx"] as const;

export function isDataFile(name: string): boolean {
  const lower = name.toLowerCase();
  return DATA_FILE_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export interface ArtifactPage {
  id: string;
  title: string;
  sql: string;
  columns: string[];
  rows: unknown[][];
  offset: number;
  total: number;
  truncated: boolean;
}

export interface DataSourceColumn {
  name: string;
  type: string;
  description: string;
  pii: boolean;
  masked: boolean; // personal data, hidden from answers for the caller's role
}

export interface DataSourceTable {
  name: string;
  description: string;
  row_estimate: number | null;
  columns: DataSourceColumn[];
}

export interface DocumentChunkText {
  chunk_no: number;
  content: string;
  heading_path: string[];
  page: number | null;
}

export interface DataSource {
  id: string;
  name: string;
  description: string;
  can_see_pii: boolean;
  tables: DataSourceTable[];
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
  warnings?: string[];
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
  error: { code: string; message: string; request_id?: string | null } | null;
}

export type TokenGetter = () => Promise<string | null>;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId: string | null = null,
  ) {
    super(requestId ? `${message} (request ${requestId.slice(0, 12)})` : message);
  }
}

// --- admin console -----------------------------------------------------------------------

export type AdminRange = "24h" | "7d" | "14d" | "30d";

export interface AdminSeriesPoint {
  bucket: string;
  requests: number;
  users: number;
  failed: number;
  succeeded: number;
  avg_duration_s: number | null;
  cost_usd: number;
  safety_events: number;
  llm_calls: number;
  tokens_in: number;
  tokens_out: number;
  cached_tokens: number;
  cache_lookups: number; // EagleEye's own cache, per bucket
  cache_hits: number;
}

export interface AdminPeriod {
  active_users: number;
  requests: number;
  succeeded: number;
  failed: number;
  cancelled: number;
  degraded: number;
  success_rate: number | null;
  failure_rate: number | null;
  avg_duration_s: number | null;
  p95_duration_s: number | null;
  avg_ttft_s: number | null;
  cost_usd: number;
  cost_per_request_usd: number | null;
  safety_events: number;
  llm_calls: number;
  tokens_in: number;
  tokens_out: number;
  cached_tokens: number;
  cache_hit_rate: number | null;
}

export type AppCacheKind = "guard" | "rewrite" | "embedding" | "answer";

/** EagleEye's own cache (guard checks, query rewrites, search embeddings, repeated answers). */
export interface AdminCaching {
  lookups: number;
  hits: number;
  hit_rate: number | null;
  saved_usd: number;
  by_kind: Record<AppCacheKind, { lookups: number; hits: number; saved_usd: number }>;
}

/** LLM spend in the current calendar month (UTC) against the organisation budget. */
export interface AdminMonthSpend {
  month_start: string; // ISO date, first of the month
  spend_usd: number;
  budget_usd: number;
  remaining_usd: number;
  used_fraction: number | null;
  alerts: number[]; // fractions of the budget, e.g. [0.75, 0.9]
}

export interface AdminModelCost {
  model_id: string;
  cost_usd: number;
  tokens: number;
  calls: number;
}

export interface AdminSlowStep {
  kind: string;
  name: string;
  executions: number;
  avg_ms: number;
  p95_ms: number;
  errors: number;
}

export interface AdminDatabaseHealth {
  status: "healthy" | "degraded" | "down";
  up: number;
  total: number;
  primary_latency_ms: number | null;
  items: { name: string; status: string; latency_ms: number | null }[];
}

export interface AdminOverview {
  range: AdminRange;
  generated_at: string;
  current: AdminPeriod;
  previous: AdminPeriod;
  total_users: number;
  series: AdminSeriesPoint[];
  cost_by_model: AdminModelCost[];
  routes: { route: string; requests: number }[];
  slow_steps: AdminSlowStep[];
  step_trend: { bucket: string; step: string; avg_ms: number; executions: number }[];
  step_change: { step: string; avg_ms: number | null; prev_avg_ms: number | null; executions: number }[];
  knowledge: { ready: number; indexing: number; failed: number; chunks: number };
  month: AdminMonthSpend;
  caching: AdminCaching;
  live: {
    databases: AdminDatabaseHealth;
    agents: { active: number; stuck: number };
  };
}

export interface AdminUserRow {
  id: string;
  email: string;
  username: string | null;
  display_name: string | null;
  role: string;
  status: string;
  last_seen_at: string | null;
  created_at: string | null;
  runs: number;
  cost_usd: number;
  tokens: number;
  last_run_at: string | null;
  lifetime_cost_usd: number;
  limit_used_pct: number | null;
}

export interface AdminUsers {
  items: AdminUserRow[];
  total: number;
  offset: number;
  usage_limit_usd: number;
}

export type AdminUserSort = "last_seen" | "cost" | "runs" | "email";

export type UserRole = "member" | "knowledge_admin" | "data_admin" | "admin";

export interface NewUserInput {
  email: string;
  /** Optional; empty means "derive from the email" (jane.doe@… → jane_doe). */
  username?: string;
  first_name: string;
  last_name: string;
  role: UserRole;
}

export interface ProvisionedUser {
  id: string;
  email: string;
  username: string | null;
  display_name: string | null;
  role: UserRole;
  status: string;
  created_at: string | null;
  last_seen_at: string | null;
}

export interface BulkUserResult {
  email: string;
  ok: boolean;
  error?: string;
  user?: ProvisionedUser;
}

export interface AdminUsage {
  by_model: { day: string; model_id: string; cost_usd: number; tokens_in: number; tokens_out: number }[];
  top_users: { email: string; cost_usd: number; runs: number }[];
  routes: { route: string; runs: number }[];
  tools: { name: string; calls: number; errors: number; avg_ms: number }[];
}

export interface AdminSafety {
  events: { kind: string; category: string; events: number }[];
  sql_rejections: { reason: string; queries: number }[];
  sql_queries: number;
  sandbox: { mode: string; status: string; runs: number; avg_ms: number }[];
  unverified_figures: { unverified: number; finished: number };
  failed_runs: { id: string; created_at: string; email: string; status: string; error_code: string | null; route: string | null }[];
  admin_actions: { created_at: string; email: string | null; category: string; detail: Record<string, unknown> }[];
}

export interface AdminContent {
  documents: { scope: string; status: string; documents: number; chunks: number }[];
  document_failures: { title: string; scope: string; error: string | null; updated_at: string }[];
  datasets: { status: string; files: number; rows: number }[];
  dataset_failures: { title: string; error: string | null; updated_at: string }[];
}

export type KillSwitchName = "chat" | "sql" | "analysis" | "uploads";

export interface AdminSystem {
  services: ServiceHealth[];
  queues: Record<string, number | null>;
  runs: { active: number; stuck: number };
  switches: { name: KillSwitchName; killed: boolean; description: string }[];
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
      const requestId = body?.error?.request_id ?? resp.headers.get("X-Request-ID");
      throw new ApiError(message, resp.status, requestId);
    }
    return body.data;
  }

  adminOverview(range: AdminRange): Promise<AdminOverview> {
    return this.request<AdminOverview>(`/v1/admin/overview?range=${range}`);
  }

  adminUsers(range: AdminRange, sort: AdminUserSort, offset: number): Promise<AdminUsers> {
    return this.request<AdminUsers>(
      `/v1/admin/users?range=${range}&sort=${sort}&offset=${offset}&limit=50`,
    );
  }

  adminUsage(range: AdminRange): Promise<AdminUsage> {
    return this.request<AdminUsage>(`/v1/admin/usage?range=${range}`);
  }

  adminSafety(range: AdminRange): Promise<AdminSafety> {
    return this.request<AdminSafety>(`/v1/admin/safety?range=${range}`);
  }

  adminContent(): Promise<AdminContent> {
    return this.request<AdminContent>("/v1/admin/content");
  }

  adminSystem(): Promise<AdminSystem> {
    return this.request<AdminSystem>("/v1/admin/system");
  }

  addUser(user: NewUserInput): Promise<ProvisionedUser> {
    return this.request<ProvisionedUser>("/v1/admin/users", {
      method: "POST",
      body: JSON.stringify(user),
    });
  }

  addUsersBulk(users: NewUserInput[]): Promise<{ results: BulkUserResult[] }> {
    return this.request("/v1/admin/users/bulk", {
      method: "POST",
      body: JSON.stringify({ users }),
    });
  }

  deleteUser(userId: string): Promise<{ id: string; deleted: boolean }> {
    return this.request(`/v1/admin/users/${userId}`, { method: "DELETE" });
  }

  setKillSwitch(name: KillSwitchName, killed: boolean): Promise<{ name: string; killed: boolean }> {
    return this.request(`/v1/admin/switches/${name}`, {
      method: "POST",
      body: JSON.stringify({ killed }),
    });
  }

  setMonthlyBudget(budgetUsd: number): Promise<{ budget_usd: number }> {
    return this.request("/v1/admin/settings/monthly-budget", {
      method: "PATCH",
      body: JSON.stringify({ budget_usd: budgetUsd }),
    });
  }

  clearStuckRuns(): Promise<{ cleared: number }> {
    return this.request("/v1/admin/runs/clear-stuck", { method: "POST" });
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

  listSources(): Promise<DataSource[]> {
    return this.request<DataSource[]>("/v1/sources");
  }

  getArtifact(artifactId: string, offset: number, limit: number): Promise<ArtifactPage> {
    return this.request<ArtifactPage>(
      `/v1/artifacts/${artifactId}?offset=${offset}&limit=${limit}`,
    );
  }

  /** Authenticated CSV download (a plain link can't carry the bearer token). */
  async downloadArtifactCsv(artifactId: string, filename: string): Promise<void> {
    const token = await this.getToken();
    const resp = await fetch(`${API_URL}/v1/artifacts/${artifactId}/csv`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!resp.ok) throw new ApiError(`Download failed (${resp.status})`, resp.status);
    const url = URL.createObjectURL(await resp.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `${filename.replace(/[^A-Za-z0-9._-]+/g, "_") || "result"}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  /** A notebook figure (PNG) fetched with the bearer token, shown from a blob URL. */
  async getNotebookFigure(notebookId: string, name: string): Promise<Blob> {
    const token = await this.getToken();
    const resp = await fetch(
      `${API_URL}/v1/notebooks/${encodeURIComponent(notebookId)}/figures/${encodeURIComponent(name)}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
    if (!resp.ok) throw new ApiError(`Could not load the figure (${resp.status})`, resp.status);
    return resp.blob();
  }

  /** Authenticated .ipynb download of a notebook. */
  async downloadNotebook(notebookId: string, title: string): Promise<void> {
    const token = await this.getToken();
    const resp = await fetch(`${API_URL}/v1/notebooks/${encodeURIComponent(notebookId)}/notebook.ipynb`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!resp.ok) throw new ApiError(`Download failed (${resp.status})`, resp.status);
    const url = URL.createObjectURL(await resp.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `${title.replace(/[^A-Za-z0-9._-]+/g, "_") || "notebook"}.ipynb`;
    link.click();
    URL.revokeObjectURL(url);
  }

  /** Liveness without signing in: false while the (sleeping) server doesn't answer. */
  async isUp(): Promise<boolean> {
    try {
      const resp = await fetch(`${API_URL}/v1/health/live`, { cache: "no-store" });
      return resp.ok;
    } catch {
      return false;
    }
  }

  /** Demo visits: counts this minute and returns the time left / whether the visit is over. */
  demoHeartbeat(): Promise<DemoVisit> {
    return this.request<DemoVisit>("/v1/demo/heartbeat", { method: "POST" });
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

  /** The original file for the viewer (fetched with the bearer token, shown from a blob URL). */
  async getDocumentFile(documentId: string): Promise<Blob> {
    const token = await this.getToken();
    const resp = await fetch(`${API_URL}/v1/documents/${documentId}/file`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!resp.ok) throw new ApiError(`Could not open the document (${resp.status})`, resp.status);
    return resp.blob();
  }

  getDocumentText(documentId: string): Promise<DocumentChunkText[]> {
    return this.request<DocumentChunkText[]>(`/v1/documents/${documentId}/text`);
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

  listDatasets(): Promise<DatasetSummary[]> {
    return this.request<DatasetSummary[]>("/v1/datasets");
  }

  getDataset(datasetId: string): Promise<DatasetDetail> {
    return this.request<DatasetDetail>(`/v1/datasets/${datasetId}`);
  }

  uploadDataset(file: File): Promise<DatasetSummary> {
    const form = new FormData();
    form.append("file", file);
    return this.request<DatasetSummary>("/v1/datasets", { method: "POST", body: form });
  }

  deleteDataset(datasetId: string): Promise<{ id: string }> {
    return this.request(`/v1/datasets/${datasetId}`, { method: "DELETE" });
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
