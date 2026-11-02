import { describe, it, expect, afterEach, vi } from "vitest";
import { isExpired, isExpiringSoon, getExpiryState } from "../helpers";

/**
 * An expiry date is a day printed on a carton, not an instant.
 *
 * `new Date("2026-09-01")` is midnight UTC, while `now.setHours(0,0,0,0)` is
 * midnight where the reader is. Subtracting one from the other put the two
 * comparisons a whole timezone offset apart, so the same carton read as
 * expiring on different days depending on which side of Greenwich you opened
 * the app -- and the badge, the "expires soon" filter and the expired flag
 * all read from these two functions, so the shift showed up three times over.
 */

const NOON = () => new Date(2026, 8, 1, 12, 0, 0); // 1 September 2026, local

function inZone(zone: string, body: () => void): void {
  const original = process.env.TZ;
  process.env.TZ = zone;
  vi.useFakeTimers();
  vi.setSystemTime(NOON());
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

describe("east of Greenwich (Europe/Warsaw, UTC+2 in September)", () => {
  it("counts a date exactly seven days out as expiring soon", () => {
    inZone("Europe/Warsaw", () => {
      expect(isExpiringSoon("2026-09-08")).toBe(true);
    });
  });

  it("does not call today expired", () => {
    inZone("Europe/Warsaw", () => {
      expect(isExpired("2026-09-01")).toBe(false);
      expect(getExpiryState("2026-09-01")).toBe("expiring");
    });
  });

  it("still calls yesterday expired", () => {
    inZone("Europe/Warsaw", () => {
      expect(isExpired("2026-08-31")).toBe(true);
      expect(getExpiryState("2026-08-31")).toBe("expired");
    });
  });

  it("leaves a date eight days out alone", () => {
    inZone("Europe/Warsaw", () => {
      expect(isExpiringSoon("2026-09-09")).toBe(false);
      expect(getExpiryState("2026-09-09")).toBe("ok");
    });
  });
});

describe("west of Greenwich (America/New_York, UTC-4 in September)", () => {
  it("does not call today expired", () => {
    inZone("America/New_York", () => {
      expect(isExpired("2026-09-01")).toBe(false);
      expect(getExpiryState("2026-09-01")).toBe("expiring");
    });
  });

  it("counts a date exactly seven days out as expiring soon", () => {
    inZone("America/New_York", () => {
      expect(isExpiringSoon("2026-09-08")).toBe(true);
    });
  });

  it("still calls yesterday expired", () => {
    inZone("America/New_York", () => {
      expect(isExpired("2026-08-31")).toBe(true);
    });
  });

  it("leaves a date eight days out alone", () => {
    inZone("America/New_York", () => {
      expect(isExpiringSoon("2026-09-09")).toBe(false);
    });
  });
});

describe("a timestamp, not a bare day", () => {
  it("is read as the day it names", () => {
    inZone("Europe/Warsaw", () => {
      expect(getExpiryState("2026-09-01T23:00:00Z")).toBe("expiring");
    });
  });
});
