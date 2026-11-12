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

export interface Envelope<T> {
  success: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
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
