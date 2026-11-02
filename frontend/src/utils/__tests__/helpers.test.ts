import { describe, it, expect } from "vitest";
import i18next from "i18next";
import {
  formatDate,
  formatDateTime,
  formatTime,
  formatMonthName,
  formatDateMedium,
  formatDateRange,
} from "../helpers";

function setLanguage(lng: string) {
  i18next.language = lng;
}

describe("formatDate", () => {
  it("returns '—' for null, undefined, empty or invalid input", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
    expect(formatDate("")).toBe("—");
    expect(formatDate("not-a-date")).toBe("—");
  });

  it("produces consistent locale-formatted output across calls", () => {
    const first = formatDate("2024-03-15T12:00:00Z");
    const second = formatDate("2024-03-15T12:00:00Z");
    const third = formatDate("2025-11-02T08:30:00Z");

    expect(first).toBe(second);
    expect(first).not.toBe(third);
    expect(first).toBe("Mar 15, 2024");
  });

  it("uses the de-DE day-first DD.MM.YYYY style", () => {
    setLanguage("de-DE");
    expect(formatDate("2024-03-15T12:00:00Z")).toBe("15.03.2024");
    setLanguage("en");
  });

  it("uses the pl-PL day-first DD.MM.YYYY style", () => {
    setLanguage("pl-PL");
    expect(formatDate("2024-03-15T12:00:00Z")).toBe("15.03.2024");
    setLanguage("en");
  });
});

describe("formatDateTime", () => {
  it("returns '—' for nullish/invalid input", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("not-a-date")).toBe("—");
  });

  it("includes a time component when the date parses", () => {
    const out = formatDateTime("2024-03-15T14:30:00Z");
    expect(out).toMatch(/\d{1,2}:\d{2}/);
  });
});

describe("formatTime", () => {
  it("returns '—' for nullish/invalid input", () => {
    expect(formatTime(null)).toBe("—");
    expect(formatTime("not-a-date")).toBe("—");
  });

  it("returns just the HH:MM portion (no date)", () => {
    const out = formatTime("2024-03-15T14:30:00Z");
    expect(out).toMatch(/^\d{1,2}:\d{2}/);
    expect(out).not.toContain("2024");
  });
});

describe("formatMonthName", () => {
  it("returns the localized long month name", () => {
    setLanguage("en");
    expect(formatMonthName(2026, 3)).toBe("March");
  });

  it("localizes to the active i18n language", () => {
    setLanguage("pl-PL");
    expect(formatMonthName(2026, 3)).toBe("marzec");
    setLanguage("de-DE");
    expect(formatMonthName(2026, 3)).toBe("März");
    setLanguage("en");
  });

  it("returns '—' for out-of-range months", () => {
    expect(formatMonthName(2026, 0)).toBe("—");
    expect(formatMonthName(2026, 13)).toBe("—");
  });
});

describe("formatDateMedium", () => {
  it("returns '—' for nullish/invalid input", () => {
    expect(formatDateMedium(null)).toBe("—");
    expect(formatDateMedium("not-a-date")).toBe("—");
  });

  it("uses the en-US 'Jul 24, 2026' medium style", () => {
    setLanguage("en-US");
    expect(formatDateMedium("2026-07-24T12:00:00Z")).toBe("Jul 24, 2026");
    setLanguage("en");
  });

  it("localizes month names per active language", () => {
    setLanguage("pl-PL");
    expect(formatDateMedium("2026-07-24T12:00:00Z")).toBe("24 lip 2026");
    setLanguage("de-DE");
    expect(formatDateMedium("2026-07-24T12:00:00Z")).toContain("Juli");
    setLanguage("en");
  });
});

describe("formatDateRange", () => {
  it("returns '—' when either date is missing", () => {
    expect(formatDateRange(null, "2026-07-30")).toBe("—");
    expect(formatDateRange("2026-07-24", null)).toBe("—");
    expect(formatDateRange(null, null)).toBe("—");
  });

  it("compacts dates within the same month", () => {
    setLanguage("en");
    expect(formatDateRange("2026-07-24", "2026-07-30")).toBe("24–30 Jul 2026");
    setLanguage("en");
  });

  it("keeps both month names when the month differs", () => {
    setLanguage("en");
    expect(formatDateRange("2026-07-24", "2026-08-02")).toBe(
      "24 Jul – 2 Aug 2026",
    );
    setLanguage("en");
  });

  it("shows full dates when the year differs", () => {
    setLanguage("en");
    expect(formatDateRange("2026-12-24", "2027-01-02")).toBe(
      "24 Dec 2026 – 2 Jan 2027",
    );
    setLanguage("en");
  });
});
