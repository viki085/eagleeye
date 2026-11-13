"use client";

import { useState } from "react";

import { Panel, Pill, SectionState, StatTile } from "@/components/admin/parts";
import { ServiceCard } from "@/components/service-card";
import { useAdminData } from "@/hooks/use-admin-data";
import { count } from "@/lib/admin-format";
import type { AdminSystem, ApiClient, KillSwitchName } from "@/lib/api";

const REFRESH_MS = 30_000;
const SWITCH_LABEL: Record<KillSwitchName, string> = {
  chat: "Chat (new questions)",
  sql: "Database querying",
  analysis: "Data analysis (sandbox)",
  uploads: "Uploads",
};

type Pending = { kind: "switch"; name: KillSwitchName; killed: boolean } | { kind: "clear" } | null;

function Confirm({ pending, busy, onConfirm, onCancel }: {
  pending: Exclude<Pending, null>;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const text =
    pending.kind === "clear"
      ? "Mark every stuck answer as failed? Their users can then ask again."
      : pending.killed
        ? `Turn off ${SWITCH_LABEL[pending.name].toLowerCase()} for everyone?`
        : `Turn ${SWITCH_LABEL[pending.name].toLowerCase()} back on?`;
  return (
    <div role="alertdialog" className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
      <span>{text}</span>
      <span className="flex gap-1.5">
        <button type="button" onClick={onCancel} disabled={busy} className="rounded border border-amber-400 px-2 py-0.5">
          Cancel
        </button>
        <button type="button" onClick={onConfirm} disabled={busy} className="rounded bg-amber-600 px-2 py-0.5 font-medium text-white disabled:opacity-50">
          {busy ? "Working…" : "Confirm"}
        </button>
      </span>
    </div>
  );
}

function Switches({ data, onAsk }: { data: AdminSystem; onAsk: (p: Pending) => void }) {
  return (
    <ul className="flex flex-col divide-y divide-neutral-100 dark:divide-neutral-800">
      {data.switches.map((s) => (
        <li key={s.name} className="flex items-center justify-between gap-3 py-2">
          <div className="min-w-0">
            <p className="text-sm font-medium">{SWITCH_LABEL[s.name]}</p>
            <p className="text-[11px] text-neutral-500">{s.killed ? s.description : "Running normally."}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Pill tone={s.killed ? "bad" : "ok"}>{s.killed ? "OFF" : "ON"}</Pill>
            <button
              type="button"
              onClick={() => onAsk({ kind: "switch", name: s.name, killed: !s.killed })}
              className="rounded border border-neutral-300 px-2 py-0.5 text-[11px] hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              {s.killed ? "Turn on" : "Turn off"}
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function SystemTab({ api }: { api: ApiClient }) {
  const [state, reload] = useAdminData(() => api.adminSystem(), [api], REFRESH_MS);
  const [pending, setPending] = useState<Pending>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const confirm = async () => {
    if (!pending) return;
    setBusy(true);
    try {
      if (pending.kind === "clear") {
        const { cleared } = await api.clearStuckRuns();
        setMessage(`${cleared} stuck answer${cleared === 1 ? "" : "s"} cleared.`);
      } else {
        await api.setKillSwitch(pending.name, pending.killed);
        setMessage(`${SWITCH_LABEL[pending.name]} turned ${pending.killed ? "off" : "on"}.`);
      }
      setPending(null);
      reload();
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionState state={state}>
      {(d) => (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Answers in progress" value={count(d.runs.active)} />
            <StatTile label="Stuck answers" value={count(d.runs.stuck)} hint="no worker heartbeat" />
            {Object.entries(d.queues).map(([queue, depth]) => (
              <StatTile key={queue} label={`Queue: ${queue}`} value={depth === null ? "?" : count(depth)} hint="tasks waiting" />
            ))}
          </div>
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            <Panel title="Controls">
              <Switches data={d} onAsk={setPending} />
              <div className="mt-2 flex items-center justify-between border-t border-neutral-100 pt-2 dark:border-neutral-800">
                <span className="text-[11px] text-neutral-500">Answers with no worker heartbeat block their chat.</span>
                <button
                  type="button"
                  disabled={d.runs.stuck === 0}
                  onClick={() => setPending({ kind: "clear" })}
                  className="rounded border border-neutral-300 px-2 py-0.5 text-[11px] hover:bg-neutral-100 disabled:opacity-40 dark:border-neutral-700 dark:hover:bg-neutral-800"
                >
                  Clear stuck answers
                </button>
              </div>
              {pending && (
                <Confirm pending={pending} busy={busy} onConfirm={() => void confirm()} onCancel={() => setPending(null)} />
              )}
              {message && <p className="mt-2 text-[11px] text-neutral-600 dark:text-neutral-300">{message}</p>}
            </Panel>
            <Panel title="Services">
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {d.services.map((s) => (
                  <ServiceCard key={s.name} service={s} />
                ))}
              </div>
            </Panel>
          </div>
          <p className="text-[11px] text-neutral-400">Refreshes every 30 s · last updated {state.kind === "ok" ? state.at.toLocaleTimeString() : "—"}</p>
        </div>
      )}
    </SectionState>
  );
}
