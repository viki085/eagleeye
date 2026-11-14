"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { monotonePath, nearestIndex, scalePoints } from "@/lib/spark";

const H = 72; // chart height, px
const PAD = 7;

export interface LineSeries {
  name: string;
  values: readonly (number | null)[];
  /** Tailwind stroke/fill classes, light and dark, e.g. "stroke-[#eb6834] dark:stroke-[#d95926]". */
  stroke: string;
  fill: string;
}

function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function Tooltip({ x, width, children }: { x: number; width: number; children: ReactNode }) {
  const left = Math.min(Math.max(x - 70, 0), Math.max(width - 140, 0));
  return (
    <div
      role="tooltip"
      style={{ left }}
      className="pointer-events-none absolute -top-2 z-20 w-[140px] -translate-y-full rounded-md border border-black/10 bg-white px-2 py-1.5 text-[11px] shadow-lg dark:border-white/10 dark:bg-[#262624]"
    >
      {children}
    </div>
  );
}

function lastIndex(values: readonly (number | null)[]): number {
  for (let i = values.length - 1; i >= 0; i--) if (values[i] !== null) return i;
  return -1;
}

/**
 * Smooth line(s) with an open dot on each series' latest value and a hover crosshair that
 * shows every series at that bucket. All series share one scale.
 */
export function GlanceLines({ series, labels, format, ariaLabel }: {
  series: readonly LineSeries[];
  labels: readonly string[];
  format: (v: number | null) => string;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const n = labels.length;
  const max = Math.max(0, ...series.flatMap((s) => s.values.map((v) => v ?? 0)));
  const scaled = width > 0 ? series.map((s) => scalePoints(s.values, width, H, max, PAD)) : [];

  return (
    <div
      ref={ref}
      className="relative h-[72px] w-full"
      onPointerMove={(e) => setHover(nearestIndex(e.clientX - e.currentTarget.getBoundingClientRect().left, width, n, PAD))}
      onPointerLeave={() => setHover(null)}
    >
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label={ariaLabel} className="overflow-visible">
          {hover !== null && scaled[0] && (
            <line x1={scaled[0][hover].x} x2={scaled[0][hover].x} y1={2} y2={H - 2} className="stroke-black/15 dark:stroke-white/20" strokeWidth={1} />
          )}
          {series.map((s, i) => {
            const pts = scaled[i];
            const last = lastIndex(s.values);
            return (
              <g key={s.name}>
                <path d={monotonePath(pts)} fill="none" strokeWidth={2} strokeLinecap="round" className={s.stroke} />
                {last >= 0 && (
                  <circle cx={pts[last].x} cy={pts[last].y} r={4} strokeWidth={2} className={`${s.stroke} fill-white dark:fill-[#1a1a19]`} />
                )}
                {hover !== null && Number.isFinite(pts[hover].y) && (
                  <circle cx={pts[hover].x} cy={pts[hover].y} r={3} className={s.fill} />
                )}
              </g>
            );
          })}
        </svg>
      )}
      {hover !== null && scaled[0] && (
        <Tooltip x={scaled[0][hover].x} width={width}>
          <p className="mb-0.5 text-neutral-500">{labels[hover]}</p>
          {series.map((s) => (
            <p key={s.name} className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1">
                <svg width="8" height="8" aria-hidden="true"><circle cx="4" cy="4" r="4" className={s.fill} /></svg>
                {s.name}
              </span>
              <span className="font-medium tabular-nums">{format(s.values[hover])}</span>
            </p>
          ))}
        </Tooltip>
      )}
    </div>
  );
}

/**
 * One bar per bucket, rounded at the top; empty buckets show as a thin dash on the baseline
 * so quiet days are visible rather than missing.
 */
export function GlanceBars({ values, labels, format, ariaLabel }: {
  values: readonly number[];
  labels: readonly string[];
  format: (v: number) => string;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const n = values.length;
  const max = Math.max(1, ...values);
  const slot = n > 0 ? (width - 2 * PAD) / n : 0;
  const gap = Math.min(10, slot * 0.25);
  const barW = Math.max(1, slot - gap);
  const base = H - PAD;

  return (
    <div ref={ref} className="relative h-[72px] w-full" onPointerLeave={() => setHover(null)}>
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label={ariaLabel}>
          {values.map((v, i) => {
            const x = PAD + i * slot + gap / 2;
            const h = (v / max) * (H - 2 * PAD);
            const on = hover === i;
            return (
              <g key={i} onPointerEnter={() => setHover(i)}>
                <rect x={PAD + i * slot} y={0} width={slot} height={H} fill="transparent" />
                {v > 0 ? (
                  <rect
                    x={x} y={base - h} width={barW} height={h} rx={Math.min(3, barW / 2)}
                    className={on ? "fill-[#4f3ec2] dark:fill-[#a79df0]" : "fill-[#6250d6] dark:fill-[#9085e9]"}
                  />
                ) : (
                  <rect x={x} y={base - 2} width={barW} height={2} rx={1} className="fill-neutral-300 dark:fill-neutral-600" />
                )}
              </g>
            );
          })}
        </svg>
      )}
      {hover !== null && (
        <Tooltip x={PAD + hover * slot + slot / 2} width={width}>
          <p className="text-neutral-500">{labels[hover]}</p>
          <p className="font-medium tabular-nums">{format(values[hover])}</p>
        </Tooltip>
      )}
    </div>
  );
}
