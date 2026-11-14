import { describe, expect, it } from "vitest";

import { datasetToken, documentToken, insertToken } from "./file-refs";

describe("tokens", () => {
  it("names a CSV by file name and a workbook sheet with its sheet", () => {
    expect(datasetToken({ filename: "brent_crude_daily.csv", sheet: "" })).toBe("[brent_crude_daily.csv]");
    expect(datasetToken({ filename: "forecast.xlsx", sheet: "Forecast" })).toBe("[forecast.xlsx (Forecast)]");
    expect(documentToken({ filename: "reefer-sop.pdf" })).toBe("[reefer-sop.pdf]");
  });
});

describe("insertToken", () => {
  it("adds spaces only where needed and moves the caret past the token", () => {
    expect(insertToken("", 0, "[a.csv]")).toEqual({ text: "[a.csv] ", caret: 8 });
    expect(insertToken("Plot", 4, "[a.csv]")).toEqual({ text: "Plot [a.csv] ", caret: 13 });
    expect(insertToken("Plot  please", 5, "[a.csv]")).toEqual({ text: "Plot [a.csv] please", caret: 13 });
    expect(insertToken("Compare and", 7, "[a.csv]")).toEqual({ text: "Compare [a.csv] and", caret: 16 });
  });

  it("clamps a caret outside the text to the end", () => {
    expect(insertToken("Hi", 99, "[a.csv]").text).toBe("Hi [a.csv] ");
  });
});
