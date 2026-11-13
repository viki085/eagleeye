import { describe, expect, it } from "vitest";

import { friendlyAuthError, safeRedirect } from "./sign-in";

const ORIGIN = "https://eagleeye.example.com";

describe("safeRedirect", () => {
  it("keeps same-origin paths and full URLs on this origin", () => {
    expect(safeRedirect("/admin", ORIGIN)).toBe("/admin");
    expect(safeRedirect(`${ORIGIN}/admin?x=1`, ORIGIN)).toBe("/admin?x=1");
  });

  it("refuses other origins, protocol-relative URLs and junk (open-redirect guard)", () => {
    for (const bad of ["https://evil.com/", "//evil.com/x", "javascript:alert(1)", "/\\evil.com", "", null]) {
      expect(safeRedirect(bad, ORIGIN)).toBe("/");
    }
  });

  it("never sends the user back to the sign-in page", () => {
    expect(safeRedirect("/sign-in/factor-one", ORIGIN)).toBe("/");
  });
});

describe("friendlyAuthError", () => {
  it("explains missing accounts in enterprise terms", () => {
    expect(friendlyAuthError("form_identifier_not_found")).toMatch(/administrator/);
  });

  it("covers wrong codes, wrong passwords and rate limits, with a fallback", () => {
    expect(friendlyAuthError("form_code_incorrect")).toMatch(/code/i);
    expect(friendlyAuthError("form_password_incorrect")).toMatch(/password/i);
    expect(friendlyAuthError("too_many_requests")).toMatch(/wait/i);
    expect(friendlyAuthError("something_new", "Server said no")).toBe("Server said no");
    expect(friendlyAuthError(undefined)).toMatch(/try again/i);
  });
});
