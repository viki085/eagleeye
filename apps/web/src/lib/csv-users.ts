/**
 * CSV import of users for the admin console. Parsed and validated in the browser so the admin
 * sees problems (with line numbers) before anything is created; the server validates again.
 */

import type { NewUserInput, UserRole } from "./api";

export const MAX_CSV_ROWS = 1000;
export const ROLES: readonly UserRole[] = ["member", "knowledge_admin", "data_admin", "admin"];
// same rule as the API (apps/api/app/routers/admin_users.py)
const EMAIL_RE = /^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$/;
const MAX_NAME = 100;
// same rule as the API: Clerk usernames are 4-64 letters, digits, '_' or '-'
export const USERNAME_RE = /^[a-z0-9_-]{4,64}$/;

export const CSV_TEMPLATE =
  "email,username,first_name,last_name,role\n" +
  "jane.doe@yourcompany.com,jane_doe,Jane,Doe,member\n" +
  "sam.lee@yourcompany.com,,Sam,Lee,knowledge_admin\n";

/** The username the server picks when none is given (mirrors clerk_admin.base_username). */
export function defaultUsername(email: string): string {
  const local = email.split("@")[0]?.toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^[_-]+|[_-]+$/g, "") ?? "";
  if (!local) return email.trim() ? "user" : "";
  return (local.length < 4 ? `${local}_user` : local).slice(0, 60);
}

const HEADER_ALIASES: Record<string, keyof NewUserInput> = {
  email: "email",
  "email address": "email",
  "e-mail": "email",
  username: "username",
  "user name": "username",
  login: "username",
  first_name: "first_name",
  "first name": "first_name",
  firstname: "first_name",
  given_name: "first_name",
  last_name: "last_name",
  "last name": "last_name",
  lastname: "last_name",
  surname: "last_name",
  family_name: "last_name",
  role: "role",
};

/** RFC 4180 parsing: quoted fields, "" escapes, commas/newlines inside quotes, CRLF, BOM. */
export function parseCsv(text: string): string[][] {
  const src = text.replace(/^﻿/, "");
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (ch === '"') {
        quoted = false;
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i += 1;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += ch;
    }
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

function normaliseRole(raw: string): UserRole | null {
  const value = raw.trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (!value) return "member";
  return (ROLES as readonly string[]).includes(value) ? (value as UserRole) : null;
}

export interface CsvRowError {
  line: number;
  email: string;
  message: string;
}

export interface ParsedUsers {
  rows: NewUserInput[];
  errors: CsvRowError[];
  fatal?: string;
}

export function parseUsersCsv(text: string): ParsedUsers {
  const table = parseCsv(text);
  const header = (table[0] ?? []).map((h) => HEADER_ALIASES[h.trim().toLowerCase()]);
  const emailCol = header.indexOf("email");
  if (emailCol === -1) {
    return { rows: [], errors: [], fatal: 'The file needs an "email" column (see the template).' };
  }
  const body = table.slice(1).map((cells, i) => ({ cells, line: i + 2 }));
  const records = body.filter(({ cells }) => cells.some((c) => c.trim() !== ""));
  if (records.length > MAX_CSV_ROWS) {
    return { rows: [], errors: [], fatal: `Up to ${MAX_CSV_ROWS} users per file; split larger lists.` };
  }
  const col = (cells: string[], key: keyof NewUserInput): string => {
    const idx = header.indexOf(key);
    return idx === -1 ? "" : (cells[idx] ?? "").trim();
  };
  const rows: NewUserInput[] = [];
  const errors: CsvRowError[] = [];
  const seen = new Set<string>();
  const seenNames = new Set<string>();
  for (const { cells, line } of records) {
    const email = col(cells, "email").toLowerCase();
    const username = col(cells, "username").toLowerCase();
    const first = col(cells, "first_name").replace(/\s+/g, " ");
    const last = col(cells, "last_name").replace(/\s+/g, " ");
    const role = normaliseRole(col(cells, "role"));
    const fail = (message: string) => errors.push({ line, email, message });
    if (!EMAIL_RE.test(email) || email.length > 254) fail(`Invalid email: "${email || "(empty)"}"`);
    else if (username && !USERNAME_RE.test(username)) fail(`Invalid username: "${username}" (4-64 letters, digits, _ or -)`);
    else if (role === null) fail(`Unknown role: "${col(cells, "role")}" (use ${ROLES.join(", ")})`);
    else if (first.length > MAX_NAME || last.length > MAX_NAME) fail(`Name too long: max ${MAX_NAME} characters`);
    else if (seen.has(email)) fail(`Duplicate email: ${email} appears earlier in the file`);
    else if (username && seenNames.has(username)) fail(`Duplicate username: ${username} appears earlier in the file`);
    else {
      seen.add(email);
      if (username) seenNames.add(username);
      rows.push({ email, first_name: first, last_name: last, role, username: username || undefined });
    }
  }
  return { rows, errors };
}

/** Splits rows into request-sized batches (the API takes 25 per call). */
export function batches<T>(items: readonly T[], size = 25): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}
