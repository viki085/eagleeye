"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { chartConfig } from "@/lib/chart-theme";

type EmbedResult = {
  view: { toImageURL: (type: "png" | "svg", scale?: number) => Promise<string> };
  finalize: () => void;
};

export interface VegaViewHandle {
  toImageURL: (type: "png" | "svg") => Promise<string | null>;
}

interface VegaViewProps {
  spec: Record<string, unknown>;
  onError?: (message: string) => void;
}

/** Follows the `.dark` class the theme toggle sets on <html>. */
export function useDarkClass(): boolean {
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

/**
 * Renders a Vega-Lite spec. Vega loads only when a chart is shown and runs with the AST
 * interpreter (`ast: true`), so no expression is compiled with eval (CSP-safe). Colours come
 * from the validated theme in lib/chart-theme.ts and follow the light/dark toggle.
 */
export const VegaView = forwardRef<VegaViewHandle, VegaViewProps>(function VegaView(
  { spec, onError },
  ref,
) {
  const host = useRef<HTMLDivElement>(null);
  const result = useRef<EmbedResult | null>(null);
  const dark = useDarkClass();

  useImperativeHandle(ref, () => ({
    toImageURL: async (type) =>
      result.current ? result.current.view.toImageURL(type, type === "png" ? 2 : 1) : null,
  }));

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
        const full = { ...spec, $schema: "https://vega.github.io/schema/vega-lite/v6.json" };
        const embedded = (await embed(el, full as never, {
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
      } catch {
        if (!cancelled) onError?.("This chart couldn't be displayed.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [spec, dark, onError]);

  useEffect(() => () => result.current?.finalize(), []);

  return <div ref={host} className="w-full min-w-0" />;
});
