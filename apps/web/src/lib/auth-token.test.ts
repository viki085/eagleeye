import { describe, expect, it } from "vitest";

import { tokenWhenReady } from "./auth-token";

const noSleep = async () => {};

describe("tokenWhenReady", () => {
  it("returns the token as soon as the session has one", async () => {
    const answers = [null, null, "tok"];
    const token = await tokenWhenReady(async () => answers.shift() ?? null, 5000, noSleep);
    expect(token).toBe("tok");
    expect(answers).toHaveLength(0);
  });

  it("gives up with null after the timeout", async () => {
    let calls = 0;
    const token = await tokenWhenReady(async () => {
      calls += 1;
      return null;
    }, 0, noSleep);
    expect(token).toBeNull();
    expect(calls).toBe(1);
  });
});
