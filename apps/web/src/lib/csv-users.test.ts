import { describe, expect, it } from "vitest";

import { CSV_TEMPLATE, MAX_CSV_ROWS, defaultUsername, parseCsv, parseUsersCsv } from "./csv-users";

describe("parseCsv", () => {
  it("handles quotes, escaped quotes, commas in fields, CRLF and a BOM", () => {
    const text = '﻿a,b\r\n"x, y","he said ""hi"""\r\n';
    expect(parseCsv(text)).toEqual([["a", "b"], ["x, y", 'he said "hi"']]);
  });
});

describe("parseUsersCsv", () => {
  it("reads the template's columns, normalising email and role", () => {
    const { rows, errors } = parseUsersCsv(
      "email,first_name,last_name,role\n  Ana@Corp.com ,Ana,Lopez,Knowledge Admin\nbo@corp.com,,,\n",
    );
    expect(errors).toEqual([]);
    expect(rows).toEqual([
      { email: "ana@corp.com", first_name: "Ana", last_name: "Lopez", role: "knowledge_admin", username: undefined },
      { email: "bo@corp.com", first_name: "", last_name: "", role: "member", username: undefined },
    ]);
  });

  it("reads an optional username column and validates it", () => {
    const { rows, errors } = parseUsersCsv(
      "email,username\na@corp.com,Ana_L\nb@corp.com,\nc@corp.com,no way\nd@corp.com,ana_l\n",
    );
    expect(rows.map((r) => r.username)).toEqual(["ana_l", undefined]);
    expect(errors.map((e) => [e.line, e.message.split(":")[0]])).toEqual([
      [4, "Invalid username"],
      [5, "Duplicate username"],
    ]);
  });

  it("derives the same default username as the server", () => {
    expect(defaultUsername("Jane.Doe@corp.com")).toBe("jane_doe");
    expect(defaultUsername("al@corp.com")).toBe("al_user");
    expect(defaultUsername("")).toBe("");
  });

  it("accepts friendly header names", () => {
    const { rows } = parseUsersCsv("Email Address,First Name,Last Name\nx@corp.com,X,Y\n");
    expect(rows[0]).toMatchObject({ email: "x@corp.com", first_name: "X", last_name: "Y" });
  });

  it("reports bad rows with their line number and keeps the good ones", () => {
    const { rows, errors } = parseUsersCsv(
      "email,role\nok@corp.com,member\nnot-an-email,member\nz@corp.com,superuser\nOK@corp.com,admin\n",
    );
    expect(rows.map((r) => r.email)).toEqual(["ok@corp.com"]);
    expect(errors.map((e) => [e.line, e.message.split(":")[0]])).toEqual([
      [3, "Invalid email"],
      [4, "Unknown role"],
      [5, "Duplicate email"],
    ]);
  });

  it("requires an email column and caps the row count", () => {
    expect(parseUsersCsv("name\nx\n").fatal).toMatch(/email/i);
    const many = ["email", ...Array.from({ length: MAX_CSV_ROWS + 1 }, (_, i) => `u${i}@corp.com`)].join("\n");
    expect(parseUsersCsv(many).fatal).toMatch(String(MAX_CSV_ROWS));
  });

  it("skips blank lines and the template parses cleanly", () => {
    expect(parseUsersCsv("email\n\n a@b.co \n\n").rows).toHaveLength(1);
    const t = parseUsersCsv(CSV_TEMPLATE);
    expect(t.errors).toEqual([]);
    expect(t.rows.length).toBeGreaterThan(0);
  });
});
