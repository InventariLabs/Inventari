import { describe, expect, it } from "vitest";
import { formatDate, formatRecentMoment, formatTime } from "@/utils/formatters";

/**
 * A journal row carries a clock time when it happened today and a date when
 * it did not. Both halves are the existing formatters, so a journal and the
 * rest of the app cannot spell the same day two ways.
 */
describe("formatRecentMoment", () => {
  const now = new Date(2026, 8, 22, 15, 0);

  it("shows the clock for a moment earlier today", () => {
    const at = new Date(2026, 8, 22, 9, 12).toISOString();
    expect(formatRecentMoment(at, now)).toBe(formatTime(at));
  });

  it("shows the date for a moment on an earlier day", () => {
    const at = new Date(2026, 8, 21, 23, 59).toISOString();
    expect(formatRecentMoment(at, now)).toBe(formatDate(at));
  });

  it("uses the reader's calendar day, not UTC's", () => {
    // Just after local midnight is today, whatever UTC says.
    const at = new Date(2026, 8, 22, 0, 5).toISOString();
    expect(formatRecentMoment(at, now)).toBe(formatTime(at));
  });

  it("falls back to the dash for a missing value", () => {
    expect(formatRecentMoment(null, now)).toBe("—");
  });
});
