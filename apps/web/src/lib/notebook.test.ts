import { describe, expect, it } from "vitest";

import { toUiMessage } from "./messages";
import { cellSummary, isNotebook, notebookTableArtifact, type NotebookView } from "./notebook";
import { foldAll } from "./run-fold";

const NOTEBOOK: NotebookView = {
  notebook_id: "nb1",
  title: "Titanic EDA",
  inputs: [{ name: "ds_1", title: "titanic" }],
  figure_count: 1,
  status: "ok",
  cells: [
    {
      index: 0, purpose: "Overview", code: "print(df.shape)", status: "ok", stdout: "(891, 12)\n",
      error: "", note: "", stats: {}, figures: [], tables: [],
    },
    {
      index: 1, purpose: "Survival by sex", code: "sns.barplot(...)", status: "ok", stdout: "",
      error: "", note: "", stats: { rate_female: 0.742 }, figures: ["fig_1_1"],
      tables: [{
        artifact_id: "a1", title: "by_sex", row_count: 2,
        columns: [{ name: "sex", type: "string" }, { name: "rate", type: "double" }],
        preview: [["female", 0.742], ["male", 0.189]],
      }],
    },
  ],
};

describe("isNotebook", () => {
  it("accepts a notebook payload and rejects other shapes", () => {
    expect(isNotebook(NOTEBOOK as unknown as Record<string, unknown>)).toBe(true);
    expect(isNotebook({ notebook_id: "x", title: "t" })).toBe(false);
    expect(isNotebook({ notebook_id: 1, title: "t", cells: [] })).toBe(false);
  });
});

describe("notebooks in answers", () => {
  it("are folded from the live notebook event", () => {
    const view = foldAll("r1", [{ event: "notebook", data: NOTEBOOK }, { event: "notebook", data: { bad: true } }]);
    expect(view.notebooks).toEqual([NOTEBOOK]);
  });

  it("are read back from a saved message", () => {
    const msg = toUiMessage({
      id: "m1",
      role: "assistant",
      created_at: "",
      run_id: "r1",
      parts: { parts: [{ type: "text", text: "Findings" }, { type: "notebooks", items: [NOTEBOOK] }] },
    } as never);
    expect(msg.notebooks.map((n) => n.notebook_id)).toEqual(["nb1"]);
  });
});

describe("notebook helpers", () => {
  it("summarises a cell for its header", () => {
    expect(cellSummary(NOTEBOOK.cells[1])).toBe("1 table · 1 figure · 1 number");
    expect(cellSummary(NOTEBOOK.cells[0])).toBe("output");
    expect(cellSummary({ ...NOTEBOOK.cells[0], stdout: "", status: "not run" })).toBe("not run");
  });

  it("turns a notebook table into an artifact for the table viewer", () => {
    const a = notebookTableArtifact(NOTEBOOK, NOTEBOOK.cells[1], NOTEBOOK.cells[1].tables[0]);
    expect(a).toMatchObject({ artifact_id: "a1", title: "Titanic EDA — by sex", mode: "python", row_count: 2 });
    expect(a.sql).toBe("sns.barplot(...)");
  });
});
