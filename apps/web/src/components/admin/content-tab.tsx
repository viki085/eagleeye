"use client";

import { DataTable, Panel, Pill, SectionState } from "@/components/admin/parts";
import { useAdminData } from "@/hooks/use-admin-data";
import { count, when } from "@/lib/admin-format";
import type { AdminContent, ApiClient } from "@/lib/api";

type DocRow = AdminContent["documents"][number];
type DocFail = AdminContent["document_failures"][number];
type DataRow = AdminContent["datasets"][number];
type DataFail = AdminContent["dataset_failures"][number];

function statusTone(status: string): "ok" | "bad" | "warn" {
  if (status === "READY") return "ok";
  if (status === "FAILED") return "bad";
  return "warn";
}

export function ContentTab({ api }: { api: ApiClient }) {
  const [state] = useAdminData(() => api.adminContent(), [api]);
  return (
    <SectionState state={state}>
      {(d) => (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          <Panel title="Documents">
            <DataTable
              rows={d.documents}
              columns={[
                { key: "scope", label: "Scope", render: (r: DocRow) => <span className="capitalize">{r.scope}</span> },
                { key: "status", label: "Status", render: (r: DocRow) => <Pill tone={statusTone(r.status)}>{r.status}</Pill> },
                { key: "n", label: "Documents", numeric: true, render: (r: DocRow) => count(r.documents) },
                { key: "chunks", label: "Chunks", numeric: true, render: (r: DocRow) => count(r.chunks) },
              ]}
            />
          </Panel>
          <Panel title="Data files">
            <DataTable
              rows={d.datasets}
              columns={[
                { key: "status", label: "Status", render: (r: DataRow) => <Pill tone={statusTone(r.status)}>{r.status}</Pill> },
                { key: "n", label: "Files", numeric: true, render: (r: DataRow) => count(r.files) },
                { key: "rows", label: "Rows", numeric: true, render: (r: DataRow) => count(r.rows) },
              ]}
            />
          </Panel>
          <Panel title="Recent document failures">
            <DataTable
              rows={d.document_failures}
              empty="No failed documents."
              columns={[
                { key: "title", label: "Document", render: (r: DocFail) => r.title },
                { key: "scope", label: "Scope", render: (r: DocFail) => <span className="capitalize">{r.scope}</span> },
                { key: "error", label: "Error", render: (r: DocFail) => r.error ?? "—" },
                { key: "when", label: "When", render: (r: DocFail) => when(r.updated_at) },
              ]}
            />
          </Panel>
          <Panel title="Recent data-file failures">
            <DataTable
              rows={d.dataset_failures}
              empty="No failed data files."
              columns={[
                { key: "title", label: "File", render: (r: DataFail) => r.title },
                { key: "error", label: "Error", render: (r: DataFail) => r.error ?? "—" },
                { key: "when", label: "When", render: (r: DataFail) => when(r.updated_at) },
              ]}
            />
          </Panel>
        </div>
      )}
    </SectionState>
  );
}
