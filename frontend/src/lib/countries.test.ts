import { describe, expect, it } from "vitest";
import {
  COUNTRY_CODES,
  countryFromLocale,
  countryLabel,
  isCountryCode,
} from "./countries";

describe("COUNTRY_CODES", () => {
  it("contains no duplicate codes", () => {
    expect(new Set(COUNTRY_CODES).size).toBe(COUNTRY_CODES.length);
  });

  it("contains only two-letter uppercase codes", () => {
    for (const code of COUNTRY_CODES) {
      expect(code).toMatch(/^[A-Z]{2}$/);
    }
  });
});

describe("isCountryCode", () => {
  it("recognises codes in the curated list", () => {
    expect(isCountryCode("PL")).toBe(true);
    expect(isCountryCode("US")).toBe(true);
  });

  it("rejects codes outside the curated list and non-strings", () => {
    expect(isCountryCode("ZZ")).toBe(false);
    expect(isCountryCode("pl")).toBe(false);
    expect(isCountryCode(null)).toBe(false);
    expect(isCountryCode(undefined)).toBe(false);
  });
});

describe("countryLabel", () => {
  it("resolves a localised label for a known code", () => {
    const label = countryLabel("PL", "en");
    expect(typeof label).toBe("string");
    expect(label.length).toBeGreaterThan(0);
    // It must actually resolve, not silently fall back to the raw code.
    expect(label).not.toBe("PL");
  });

  it("falls back to the code when Intl cannot resolve it", () => {
    expect(countryLabel("XX", "en")).toBe("XX");
  });
});

describe("countryFromLocale", () => {
  it("reads the region a locale names", () => {
    expect(countryFromLocale("de-DE")).toBe("DE");
    expect(countryFromLocale("en-GB")).toBe("GB");
  });

  it("falls back to the language's likeliest region", () => {
    expect(countryFromLocale("pl")).toBe("PL");
  });

  it("suggests nothing for a region outside the list or a locale it cannot read", () => {
    expect(countryFromLocale("en-SG")).toBeNull();
    expect(countryFromLocale("not a locale")).toBeNull();
    expect(countryFromLocale("")).toBeNull();
    expect(countryFromLocale(undefined)).toBeNull();
  });
});
