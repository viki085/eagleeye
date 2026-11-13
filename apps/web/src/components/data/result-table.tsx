"use client";

const NUMBER_FORMAT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

const ID_COLUMN = /(^id$|_id$|^id_)/i;

function formatCell(value: unknown, isId: boolean): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return isId ? String(value) : NUMBER_FORMAT.format(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

interface ResultTableProps {
  columns: readonly string[];
  rows: readonly (readonly unknown[])[];
  maxHeightClass?: string;
}

/** Plain text cells (never HTML); numbers right-aligned with tabular figures. */
export function ResultTable({ columns, rows, maxHeightClass = "max-h-72" }: ResultTableProps) {
  const numeric = columns.map((_, i) =>
    rows.length > 0 && rows.every((r) => r[i] === null || typeof r[i] === "number"),
  );
  return (
    <div className={`overflow-auto rounded-md border border-neutral-200 dark:border-neutral-800 ${maxHeightClass}`}>
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 bg-neutral-100 dark:bg-neutral-900">
          <tr>
            {columns.map((c, i) => (
              <th
                key={`${c}-${i}`}
                scope="col"
                className={`whitespace-nowrap border-b border-neutral-200 px-2.5 py-1.5 font-semibold text-neutral-700 dark:border-neutral-800 dark:text-neutral-300 ${
                  numeric[i] ? "text-right" : "text-left"
                }`}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="odd:bg-white even:bg-neutral-50 dark:odd:bg-neutral-950 dark:even:bg-neutral-900/50">
              {row.map((cell, i) => (
                <td
                  key={i}
                  className={`whitespace-nowrap border-b border-neutral-100 px-2.5 py-1 text-neutral-800 dark:border-neutral-900 dark:text-neutral-200 ${
                    numeric[i] ? "text-right tabular-nums" : ""
                  }`}
                >
                  {formatCell(cell, ID_COLUMN.test(columns[i] ?? ""))}
                </td>
              ))}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-2.5 py-3 text-center text-neutral-400">
                No rows
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
