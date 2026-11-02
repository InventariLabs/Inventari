import { afterEach, describe, expect, it, vi } from "vitest";
import i18next from "i18next";
import {
  dateFnsLocale,
  formatDate,
  formatDateMedium,
  formatDateRange,
  formatMonthName,
  setOrganizationCountry,
} from "../formatters";

describe("English follows the organization's region", () => {
  const original = i18next.language;
  afterEach(async () => {
    setOrganizationCountry(null);
    await i18next.changeLanguage(original || "en");
  });

  it("keeps US conventions for a US organization", () => {
    setOrganizationCountry("US");
    expect(formatDate("2026-04-03")).toBe("Apr 3, 2026");
  });

  it("writes day before month for an English reader outside the US", () => {
    setOrganizationCountry("GB");
    expect(formatDate("2026-04-03")).toBe("3 Apr 2026");
    expect(formatDateMedium("2026-04-03")).toBe("3 Apr 2026");
    expect(dateFnsLocale().code).toBe("en-GB");
  });

  it("applies to any non-US country, not only the United Kingdom", () => {
    setOrganizationCountry("nl");
    expect(formatDate("2026-04-03")).toBe("3 Apr 2026");
  });

  it("stays American when the organization has no country, whatever the browser says", () => {
    setOrganizationCountry(null);
    const region = vi
      .spyOn(navigator, "language", "get")
      .mockReturnValue("en-GB");
    try {
      expect(formatDate("2026-04-03")).toBe("Apr 3, 2026");
    } finally {
      region.mockRestore();
    }
  });

  it("ignores a regional tag on the interface language, as a printout cannot see it", async () => {
    setOrganizationCountry(null);
    await i18next.changeLanguage("en-GB");
    expect(formatDate("2026-04-03")).toBe("Apr 3, 2026");
    setOrganizationCountry("GB");
    expect(formatDate("2026-04-03")).toBe("3 Apr 2026");
  });

  it("leaves other languages alone", async () => {
    setOrganizationCountry("GB");
    await i18next.changeLanguage("pl");
    expect(formatDate("2026-04-03")).toBe("03.04.2026");
    expect(dateFnsLocale().code).toBe("pl");
  });

  it("applies to range and month-name formatters", () => {
    setOrganizationCountry("IE");
    expect(formatDateRange("2026-04-03", "2026-04-09")).toBe("3–9 Apr 2026");
    expect(formatMonthName(2026, 9)).toBe("September");
  });
});
