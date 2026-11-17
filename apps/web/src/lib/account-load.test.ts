import { describe, expect, it } from "vitest";

import { accountLoadFailure, displayRole } from "./account-load";
import { ApiError } from "./api";

describe("accountLoadFailure", () => {
  it("treats a 403 as no EagleEye account", () => {
    expect(accountLoadFailure(new ApiError("No access", 403))).toBe("no_access");
  });

  it("checks the server on CloudFront's error page while the machine is off", () => {
    expect(accountLoadFailure(new ApiError("Bad gateway", 502))).toBe("check_server");
    expect(accountLoadFailure(new ApiError("Gateway timeout", 504))).toBe("check_server");
  });

  it("checks the server when there is no reply at all", () => {
    expect(accountLoadFailure(new TypeError("Failed to fetch"))).toBe("check_server");
  });
});

describe("displayRole", () => {
  it("shows no role until the account has loaded", () => {
    expect(displayRole(null)).toBeUndefined();
    expect(displayRole(undefined)).toBeUndefined();
  });

  it("shows the loaded role", () => {
    expect(displayRole({ isAdmin: true })).toBe("admin");
    expect(displayRole({ isAdmin: false })).toBe("member");
  });
});
