import { afterEach, describe, expect, it, vi } from "vitest";
import { formatDate, formatDateMedium, formatDateRange } from "../formatters";

/**
 * A SQL DATE serializes to "2026-09-06" — a calendar day, no time part.
 * `new Date("2026-09-06")` reads it as UTC midnight, so a reader west of
 * UTC saw the previous day than the one written: a repair done on 6
 * September showed as 5 September in New York. These tests pin the
 * calendar-day contract from both sides of Greenwich; they are meaningful
 * only because the zone is switched per test (process.env.TZ), which is
 * why every case runs through `inZone`.
 */
function inZone(zone: string, body: () => void): void {
  const original = process.env.TZ;
  process.env.TZ = zone;
  try {
    body();
  } finally {
    process.env.TZ = original;
  }
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("a date without a time is the day that was written", () => {
  it("a west-of-UTC reader sees the written day, not the previous one", () => {
    inZone("America/New_York", () => {
      expect(formatDate("2026-09-06")).toBe("Sep 6, 2026");
    });
  });

  it("an east-of-UTC reader sees it too", () => {
    inZone("Europe/Warsaw", () => {
      expect(formatDate("2026-09-06")).toBe("Sep 6, 2026");
    });
  });

  it("formatDateMedium names the written day west of UTC", () => {
    inZone("America/New_York", () => {
      expect(formatDateMedium("2026-09-06")).toBe("Sep 6, 2026");
    });
  });

  it("formatDateRange keeps both written days", () => {
    inZone("America/New_York", () => {
      expect(formatDateRange("2026-09-06", "2026-09-20")).toBe("6–20 Sep 2026");
    });
  });

  it("a full timestamp still converts to the reader's zone", () => {
    // The no-conversion rule is for calendar days only: an instant on the
    // timeline must keep rendering in the reader's zone (23:00 UTC on the
    // 5th is 19:00 on the 5th in New York, and the day shown is the 5th).
    inZone("America/New_York", () => {
      expect(formatDate("2026-09-06T03:00:00Z")).toBe("Sep 5, 2026");
    });
  });
});
