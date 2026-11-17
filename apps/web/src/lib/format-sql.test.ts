import { format } from "sql-formatter";
import { describe, expect, it } from "vitest";

import { formatQuery } from "./format-sql";

const fmt = format as unknown as Parameters<typeof formatQuery>[0];

describe("formatQuery", () => {
  it("puts each clause on its own line, indented, keywords in capitals", () => {
    const sql =
      "select tl.lane_code as trade_lane, round(count(*) filter (where pc.actual_arrival <= pc.scheduled_arrival + interval '24 hours')::numeric / nullif(count(*), 0) * 100, 2) as on_time_pct from ops.port_calls pc join ops.trade_lanes tl on tl.id = pc.lane_id where pc.scheduled_arrival >= '2026-01-01' group by tl.lane_code order by on_time_pct desc";
    const out = formatQuery(fmt, sql, "sql");
    const lines = out.split("\n");
    expect(lines[0]).toBe("SELECT");
    expect(lines).toContain("FROM");
    expect(lines.some((l) => l.startsWith("  JOIN ops.trade_lanes tl"))).toBe(true);
    expect(lines).toContain("GROUP BY");
    expect(out).toContain("ORDER BY");
    expect(out).toContain("'24 hours'"); // literals untouched
    expect(out).toContain("tl.lane_code"); // identifiers keep their case
  });

  it("formats DuckDB analysis queries", () => {
    const out = formatQuery(fmt, "select trade_lane, count(*) filter (where nps >= 9) as promoters from ds_1 group by 1", "duckdb");
    expect(out.split("\n")[0]).toBe("SELECT");
    expect(out).toContain("FROM\n  ds_1");
  });

  it("leaves Python and unparseable text exactly as written", () => {
    expect(formatQuery(fmt, "df.groupby('lane').nps.mean()", "python")).toBe("df.groupby('lane').nps.mean()");
    const broken = "select from where ((";
    expect(formatQuery(() => { throw new Error("parse"); }, broken, "sql")).toBe(broken);
  });
});
