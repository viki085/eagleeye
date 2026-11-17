"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

import { useDarkClass, type VegaViewHandle } from "@/components/charts/vega-view";
import type { EChartsOption } from "@/lib/echarts-option";

type ECharts = {
  setOption: (option: EChartsOption, notMerge?: boolean) => void;
  resize: () => void;
  dispose: () => void;
  getDataURL: (opts: { type: "png" | "svg"; pixelRatio?: number; backgroundColor?: string }) => string;
};
type Core = { init: (el: HTMLElement, theme?: null, opts?: { renderer: "canvas" | "svg" }) => ECharts };

let loaded: Promise<Core> | null = null;

/** Only the chart types and parts we draw (keeps the download small); loaded on first chart. */
function loadECharts(): Promise<Core> {
  loaded ??= (async () => {
    const [core, charts, components, renderers] = await Promise.all([
      import("echarts/core"),
      import("echarts/charts"),
      import("echarts/components"),
      import("echarts/renderers"),
    ]);
    core.use([
      charts.BarChart, charts.LineChart, charts.ScatterChart, charts.HeatmapChart, charts.PieChart,
      components.GridComponent, components.TooltipComponent, components.LegendComponent,
      components.TitleComponent,
      components.DataZoomComponent, components.VisualMapComponent,
      renderers.CanvasRenderer, renderers.SVGRenderer,
    ]);
    return core as unknown as Core;
  })();
  return loaded;
}

interface EChartViewProps {
  option: (dark: boolean) => EChartsOption | null;
  height: number;
  onError?: (message: string) => void;
}

/** Draws an ECharts option (canvas), follows the light/dark toggle and resizes with its card.
 * Exposes the same toImageURL as VegaView, so the card's PNG/SVG buttons work with either. */
export const EChartView = forwardRef<VegaViewHandle, EChartViewProps>(function EChartView(
  { option, height, onError },
  ref,
) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts | null>(null);
  const dark = useDarkClass();

  useImperativeHandle(ref, () => ({
    toImageURL: async (type) => {
      const current = option(dark);
      if (!chart.current || !current) return null;
      const background = dark ? "#0a0a0a" : "#ffffff";
      if (type === "png") return chart.current.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: background });
      // SVG: draw the same option once more with the SVG renderer, off screen
      const core = await loadECharts();
      const el = document.createElement("div");
      el.style.cssText = `position:fixed;left:-10000px;width:${host.current?.clientWidth ?? 800}px;height:${height}px`;
      document.body.appendChild(el);
      try {
        const svg = core.init(el, null, { renderer: "svg" });
        svg.setOption({ ...current, animation: false }, true);
        const url = svg.getDataURL({ type: "svg", backgroundColor: background });
        svg.dispose();
        return url;
      } finally {
        el.remove();
      }
    },
  }));

  useEffect(() => {
    let cancelled = false;
    const el = host.current;
    if (!el) return;
    (async () => {
      try {
        const opt = option(dark);
        if (!opt) throw new Error("unsupported chart");
        const core = await loadECharts();
        if (cancelled) return;
        chart.current ??= core.init(el, null, { renderer: "canvas" });
        chart.current.setOption(opt, true);
      } catch (e) {
        onError?.(e instanceof Error ? e.message : "chart failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [option, dark, onError]);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(el);
    return () => {
      observer.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  return <div ref={host} style={{ width: "100%", height }} />;
});
