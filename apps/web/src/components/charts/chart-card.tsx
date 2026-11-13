"use client";

import { useEffect, useRef, useState } from "react";

import type { ChartView } from "@/lib/api";
import { chartConfig } from "@/lib/chart-theme";

interface ChartCardProps {
  chart: ChartView;
}

type EmbedResult = {
  view: { toImageURL: (type: "png" | "svg", scale?: number) => Promise<string> };
  finalize: () => void;
};

const BUTTON =
  "rounded-md border border-neutral-300 px-2 py-0.5 text-[11px] text-neutral-600 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800";

/** Follows the `.dark` class the theme toggle sets on <html>. */
function useDarkClass(): boolean {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const root = document.documentElement;
    const read = () => setDark(root.classList.contains("dark"));
    read();
    const observer = new MutationObserver(read);
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return dark;
}

function safeName(title: string): string {
  return title.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "chart";
}

/**
 * Renders a server-built Vega-Lite spec. Vega is loaded only when a chart is shown, and
 * runs with the AST interpreter (`ast: true`) so no expression is ever compiled with eval.
 */
export function ChartCard({ chart }: ChartCardProps) {
  const host = useRef<HTMLDivElement>(null);
  const result = useRef<EmbedResult | null>(null);
  const dark = useDarkClass();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const el = host.current;
    if (!el) return;
    (async () => {
      try {
        const [{ default: embed }, { expressionInterpreter }] = await Promise.all([
          import("vega-embed"),
          import("vega-interpreter"),
        ]);
        if (cancelled) return;
        const spec = { ...chart.spec, $schema: "https://vega.github.io/schema/vega-lite/v6.json" };
        const embedded = (await embed(el, spec as never, {
          mode: "vega-lite",
          renderer: "svg",
          actions: false,
          ast: true,
          expr: expressionInterpreter,
          config: chartConfig(dark) as never,
          tooltip: true,
        })) as unknown as EmbedResult;
        if (cancelled) {
          embedded.finalize();
          return;
        }
        result.current?.finalize();
        result.current = embedded;
        setError(null);
      } catch {
        if (!cancelled) setError("This chart couldn't be displayed. The result table below has the data.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chart.spec, dark]);

  useEffect(() => () => result.current?.finalize(), []);

  const download = async (type: "png" | "svg") => {
    if (!result.current) return;
    try {
      const url = await result.current.view.toImageURL(type, type === "png" ? 2 : 1);
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
      <div ref={host} className="w-full min-w-0" />
      {error && <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">{error}</p>}
      <p className="sr-only">{chart.summary}</p>
    </figure>
  );
}
