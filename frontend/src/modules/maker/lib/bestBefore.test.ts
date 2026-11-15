import { describe, expect, it } from "vitest";
import { defaultBestBefore } from "@/modules/maker/lib/bestBefore";

describe("the best-before a run proposes", () => {
  it("is the day it was made plus the shelf life", () => {
    expect(defaultBestBefore("2025-11-02", 180)).toBe("2026-05-01");
  });

  it("crosses a month end on the calendar, not in thirty-day steps", () => {
    expect(defaultBestBefore("2026-01-31", 1)).toBe("2026-02-01");
  });

  it("proposes nothing without a shelf life", () => {
    expect(defaultBestBefore("2025-11-02", null)).toBe("");
    expect(defaultBestBefore("2025-11-02", undefined)).toBe("");
  });
});
