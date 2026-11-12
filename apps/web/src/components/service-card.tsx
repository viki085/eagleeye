import type { ServiceHealth } from "@/lib/api";

const LABELS: Record<string, string> = {
  redis: "Redis",
  qdrant: "Qdrant",
  "object-store": "Object Store (SeaweedFS)",
  "supabase-pg": "Supabase Postgres",
};

interface ServiceCardProps {
  service: ServiceHealth;
}

export function ServiceCard({ service }: ServiceCardProps) {
  const up = service.status === "up";
  return (
    <div className="flex items-center justify-between rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
      <div>
        <p className="text-sm font-medium">{LABELS[service.name] ?? service.name}</p>
        <p className="mt-0.5 text-xs text-neutral-500">
          {up ? `${service.latency_ms ?? "—"} ms` : (service.detail ?? "unreachable")}
        </p>
      </div>
      <span
        className={
          up
            ? "inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300"
            : "inline-flex items-center gap-1.5 rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-700 dark:bg-red-900 dark:text-red-300"
        }
      >
        <span className={up ? "h-1.5 w-1.5 rounded-full bg-emerald-500" : "h-1.5 w-1.5 rounded-full bg-red-500"} />
        {up ? "up" : "down"}
      </span>
    </div>
  );
}
