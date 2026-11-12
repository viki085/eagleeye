"use client";

import { compactNumber, percent } from "@/lib/format";

interface TokenSplitProps {
  tokensIn: number;
  tokensOut: number;
}

function Swatch({ color }: { color: string }) {
  return <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />;
}

/** Thin segmented bar (one whole, two parts) with a legend — identity never by colour alone. */
export function TokenSplit({ tokensIn, tokensOut }: TokenSplitProps) {
  const total = tokensIn + tokensOut;
  const inShare = total > 0 ? tokensIn / total : 0;
  const outShare = total > 0 ? tokensOut / total : 0;

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium text-neutral-700 dark:text-neutral-300">Tokens</span>
        <span className="text-xs tabular-nums text-neutral-500 dark:text-neutral-400">
          {compactNumber(total)} total
        </span>
      </div>
      <div
        role="img"
        aria-label={`Input ${compactNumber(tokensIn)} tokens (${percent(inShare)}), output ${compactNumber(tokensOut)} tokens (${percent(outShare)})`}
        className="mt-1.5 flex h-2 w-full gap-[2px]"
      >
        {total === 0 ? (
          <div className="h-full w-full rounded-full bg-neutral-200 dark:bg-neutral-800" />
        ) : (
          <>
            {tokensIn > 0 && (
              <div
                title={`Input: ${tokensIn.toLocaleString("en-US")} tokens`}
                className="h-full rounded-full"
                style={{ width: `${inShare * 100}%`, background: "var(--viz-input)" }}
              />
            )}
            {tokensOut > 0 && (
              <div
                title={`Output: ${tokensOut.toLocaleString("en-US")} tokens`}
                className="h-full rounded-full"
                style={{ width: `${outShare * 100}%`, background: "var(--viz-output)" }}
              />
            )}
          </>
        )}
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] text-neutral-600 dark:text-neutral-400">
        <span className="flex items-center gap-1.5">
          <Swatch color="var(--viz-input)" />
          Input <span className="tabular-nums text-neutral-900 dark:text-neutral-100">{compactNumber(tokensIn)}</span>
        </span>
        <span className="flex items-center gap-1.5">
          <Swatch color="var(--viz-output)" />
          Output <span className="tabular-nums text-neutral-900 dark:text-neutral-100">{compactNumber(tokensOut)}</span>
        </span>
      </div>
    </div>
  );
}
