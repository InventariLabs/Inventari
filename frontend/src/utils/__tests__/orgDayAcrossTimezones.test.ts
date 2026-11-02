import { describe, it, expect, afterEach, vi } from "vitest";
import { formatDate, formatDateInZone } from "../formatters";

/**
 * An org-clock day is a day on the organization's calendar, not the
 * reader's.
 *
 * The backend pins an attestation deadline to 23:59:59.999999 in the
 * organization's zone and stores the UTC instant. Formatting that instant
 * in the browser's zone moved the day: a Warsaw reader (UTC+2) opening a
 * campaign pinned to the 25th in New York saw the 26th on the list the
 * second after the form said 25. `formatDateInZone` reads the instant
 * through the organization's clock instead, and the reproduction below
 * flips both directions across the dateline. Calendar days (date-only
 * strings) stay zone-free and keep the `formatDate` path.
 */

function inZone(zone: string, body: () => void): void {
  const original = process.env.TZ;
  process.env.TZ = zone;
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 8, 22, 12, 0, 0));
  try {
    body();
  } finally {
    vi.useRealTimers();
    process.env.TZ = original;
  }
}

afterEach(() => {
  vi.useRealTimers();
});

describe("org west of the reader (org UTC-4, reader UTC+2)", () => {
  // End of the org's 25 September in New York, as the API serializes it.
  const deadline = "2026-09-26T03:59:59.999999Z";

  it("the reader's own clock moves the day to the 26th — the reported bug", () => {
    inZone("Europe/Warsaw", () => {
      expect(formatDate(deadline)).toBe("Sep 26, 2026");
    });
  });

  it("the organization's clock keeps the day the org picked", () => {
    inZone("Europe/Warsaw", () => {
      expect(formatDateInZone(deadline, "America/New_York")).toBe(
        "Sep 25, 2026",
      );
    });
  });
});

describe("org west of the reader (org UTC+14, reader UTC-11)", () => {
  // End of the org's 25 September in Kiritimati — the reader would land on
  // the 24th, the mirror of the reported direction.
  const deadline = "2026-09-25T09:59:59.999999Z";

  it("the reader's own clock moves the day back to the 24th", () => {
    inZone("Pacific/Pago_Pago", () => {
      expect(formatDate(deadline)).toBe("Sep 24, 2026");
    });
  });

  it("the organization's clock keeps the day the org picked", () => {
    inZone("Pacific/Pago_Pago", () => {
      expect(formatDateInZone(deadline, "Pacific/Kiritimati")).toBe(
        "Sep 25, 2026",
      );
    });
  });
});

describe("calendar days stay zone-free", () => {
  it("a date-only string shows the written day whatever zone is passed", () => {
    inZone("Europe/Warsaw", () => {
      expect(formatDateInZone("2026-09-25", "America/New_York")).toBe(
        "Sep 25, 2026",
      );
    });
  });

  it("an unknown zone renders the reader's clock, like formatDate", () => {
    inZone("Europe/Warsaw", () => {
      expect(formatDateInZone("2026-09-26T03:59:59.999999Z", undefined)).toBe(
        formatDate("2026-09-26T03:59:59.999999Z"),
      );
    });
  });

  it("a missing value renders the em-dash placeholder", () => {
    inZone("Europe/Warsaw", () => {
      expect(formatDateInZone(null, "America/New_York")).toBe("\u2014");
    });
  });
});
