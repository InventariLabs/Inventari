/**
 * The ratchet counts what it is named after: sleeps, not words that merely
 * contain the name.
 */
import { describe, expect, it } from "vitest";

import { countWaits } from "./check-e2e-wait-for-timeout.mjs";

describe("countWaits", () => {
  it("counts each page.waitForTimeout call", () => {
    const text = `await page.waitForTimeout(500);\nawait page.waitForTimeout (2000);`;
    expect(countWaits(text)).toBe(2);
  });

  it("ignores a mention that is not a call", () => {
    expect(countWaits("// avoid waitForTimeout, poll instead")).toBe(0);
  });
});
