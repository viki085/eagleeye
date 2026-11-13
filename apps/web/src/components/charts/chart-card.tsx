"use client";

import { useCallback, useRef, useState } from "react";

import { VegaView, type VegaViewHandle } from "@/components/charts/vega-view";
import type { ChartView } from "@/lib/api";

interface ChartCardProps {
  chart: ChartView;
}

const BUTTON =
  "rounded-md border border-neutral-300 px-2 py-0.5 text-[11px] text-neutral-600 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800";

function safeName(title: string): string {
  return title.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "chart";
}

/** A server-built chart under an answer, with PNG/SVG export. */
export function ChartCard({ chart }: ChartCardProps) {
  const view = useRef<VegaViewHandle>(null);
  const [error, setError] = useState<string | null>(null);
  const onError = useCallback(
    () => setError("This chart couldn't be displayed. The result table below has the data."),
    [],
  );

  const download = async (type: "png" | "svg") => {
    try {
      const url = await view.current?.toImageURL(type);
      if (!url) return;
      const link = document.createElement("a");
      link.href = url;
      link.download = `${safeName(chart.title)}.${type}`;
      link.click();
    } catch {
      setError("Export failed.");
    }
  };

  return (
    <figure
      // `relative`: the sr-only summary is position:absolute; without a positioned parent it
      // escapes the chat's scroll area and stretches the whole page (blank space on scroll)
      className="relative mt-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
      aria-label={`Chart: ${chart.title}. ${chart.summary}`}
    >
      <figcaption className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
          {chart.title}
        </span>
        <span className="flex gap-1.5">
          <button type="button" className={BUTTON} onClick={() => void download("png")}>
            PNG
          </button>
          <button type="button" className={BUTTON} onClick={() => void download("svg")}>
            SVG
          </button>
        </span>
      </figcaption>
      <VegaView ref={view} spec={chart.spec} onError={onError} />
      {error && <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">{error}</p>}
      <p className="sr-only">{chart.summary}</p>
    </figure>
  );
}
