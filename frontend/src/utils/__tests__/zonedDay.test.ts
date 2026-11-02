import { describe, it, expect, afterEach, vi } from "vitest";
import { instantInsideDay } from "../zonedDay";
import { formatDateInZone } from "../formatters";

/**
 * The write side of the org-day contract.
 *
 * The backend reads an arrival through the organization's clock and pins
 * the end of the day it sees there. A form that sent the picked day in the
 * browser's zone stored the next day for every organization east of the
 * reader — the walk below sends the instant the form now sends, reads it
 * back through the org clock, and requires the picked day to survive.
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
  vi.useRealTimers();
});

describe("instantInsideDay", () => {
  it("a Tokyo organization receives noon of the picked day (03:00Z)", () => {
    expect(instantInsideDay("2026-09-30", "Asia/Tokyo").toISOString()).toBe(
      "2026-09-30T03:00:00.000Z",
    );
  });

  it("a New York organization receives noon of the picked day (16:00Z)", () => {
    expect(
      instantInsideDay("2026-09-30", "America/New_York").toISOString(),
    ).toBe("2026-09-30T16:00:00.000Z");
  });

  it("an unknown org zone falls back to the browser's noon", () => {
    inZone("Europe/Warsaw", () => {
      expect(instantInsideDay("2026-09-30", undefined).toISOString()).toBe(
        "2026-09-30T10:00:00.000Z",
      );
    });
  });

  it("noon survives a DST day (the transition happens at night)", () => {
    // 2026-03-08 is the US spring-forward day; 23:59:59 does not exist in
    // some zones, noon always does.
    expect(
      instantInsideDay("2026-03-08", "America/New_York").toISOString(),
    ).toBe("2026-03-08T16:00:00.000Z");
  });
});

describe("the arrival lands inside the org's day", () => {
  const cases: Array<[string, string, string]> = [
    // [org zone, picked day, the day the org clock must read off the arrival]
    ["Asia/Tokyo", "2026-09-30", "Sep 30, 2026"],
    ["America/New_York", "2026-09-30", "Sep 30, 2026"],
    ["Europe/Warsaw", "2026-01-05", "Jan 5, 2026"],
  ];

  for (const [orgZone, pickedDay, orgDay] of cases) {
    it(`${pickedDay} reads as ${orgDay} on an org clock in ${orgZone}`, () => {
      const arrival = instantInsideDay(pickedDay, orgZone);
      // The backend reads this instant through the org clock; the day it
      // sees there is the day it pins. A reader as far west as the dateline
      // allows must read the same day off the stored value.
      inZone("Pacific/Pago_Pago", () => {
        expect(formatDateInZone(arrival.toISOString(), orgZone)).toBe(orgDay);
      });
    });
  }
});
