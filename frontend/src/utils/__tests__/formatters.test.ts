import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18next from "i18next";
import {
  formatMoney,
  currencySymbol,
  decimalsAllowedBy,
  formatQuantity,
  formatQuantityValue,
  formatQuantityLocale,
  formatNumberLocale,
  formatPercentLocale,
  formatBytes,
  formatDecimalQty,
  getTodayFilename,
  todayIso,
} from "../formatters";

describe("formatMoney — locale-aware currency", () => {
  it("returns em-dash for null/empty/non-finite amounts", () => {
    expect(formatMoney(null)).toBe("\u2014");
    expect(formatMoney(undefined)).toBe("\u2014");
    expect(formatMoney("")).toBe("\u2014");
    expect(formatMoney("not-a-number")).toBe("\u2014");
    expect(formatMoney(NaN)).toBe("\u2014");
  });

  it("locale-formats a number without currency (PL)", () => {
    const out = formatMoney(1200, undefined, "pl-PL");
    expect(out).not.toContain("PLN");
    expect(out).toMatch(/1200|1\s*200/);
  });

  it("locale-formats a number without currency (EN)", () => {
    const out = formatMoney(1200, undefined, "en-US");
    expect(out).not.toContain("PLN");
    expect(out).toMatch(/1200|1,200/);
  });

  it("renders PLN with symbol in Polish locale", () => {
    const out = formatMoney(1200, "PLN", "pl-PL");
    expect(out).toMatch(/zł|PLN/);
    expect(out).toMatch(/1200|1\s*200/);
  });

  it("renders EUR with symbol in German locale", () => {
    const out = formatMoney(1200, "EUR", "de-DE");
    expect(out).toMatch(/€|EUR/);
    expect(out).toMatch(/1200|1\.200/);
  });

  it("renders USD with symbol in English locale", () => {
    const out = formatMoney(1234.5, "USD", "en-US");
    expect(out).toMatch(/\$|USD/);
    expect(out).toMatch(/1234|1,234/);
  });

  it("accepts numeric strings", () => {
    const out = formatMoney("1200.00", "PLN", "pl-PL");
    expect(out).toMatch(/zł|PLN/);
  });

  it("falls back gracefully on invalid currency codes", () => {
    const out = formatMoney(99.5, "BOGUS", "en-US");
    expect(out).toContain("99");
    expect(out).not.toBe("\u2014");
  });

  // In the locales whose currency pattern puts the currency after the
  // amount, a separator stands between the two — the pattern is
  // "6,00 USD", never "6,00USD". The separator Intl writes is the
  // non-breaking space (U+00A0), so the assertion accepts any whitespace.
  // English is the counter-shape: the symbol precedes the amount ($6.00),
  // so it is documented here only to say the difference is expected.
  describe("the separator between the amount and the currency", () => {
    it("keeps the space before the currency code in Polish (USD)", () => {
      const out = formatMoney(6, "USD", "pl");
      expect(out).toMatch(/6,00[\s\u00a0]USD/);
    });

    it("keeps the space before the symbol in Polish (PLN)", () => {
      const out = formatMoney(6, "PLN", "pl");
      expect(out).toMatch(/6,00[\s\u00a0]zł/);
    });

    it("keeps the space before the symbol in German, French and Spanish", () => {
      expect(formatMoney(6, "USD", "de")).toMatch(/6,00[\s\u00a0]\$/);
      // The currency code belongs in the pattern: with only the separator
      // asserted, the test stays green on a formatting that drops it.
      expect(formatMoney(6, "USD", "fr")).toMatch(/6,00[\s\u00a0]\$US/);
      expect(formatMoney(6, "USD", "es")).toMatch(/6,00[\s\u00a0]US\$/);
    });

    it("English puts the symbol first — no trailing-code shape to separate", () => {
      expect(formatMoney(6, "USD", "en")).toMatch(/^\$/);
    });
  });
});

describe("currencySymbol — approval threshold prefix", () => {
  it("extracts the currency symbol for common codes", () => {
    expect(currencySymbol("EUR", "de-DE")).toMatch(/€|EUR/);
    expect(currencySymbol("USD", "en-US")).toMatch(/\$|USD/);
    expect(currencySymbol("PLN", "pl-PL")).toMatch(/zł|PLN/);
  });

  it("returns an empty string when no currency is given", () => {
    expect(currencySymbol(null)).toBe("");
    expect(currencySymbol(undefined)).toBe("");
    expect(currencySymbol("")).toBe("");
  });

  it("falls back to the raw currency code when Intl cannot format it", () => {
    expect(currencySymbol("BOGUS", "en-US")).toBe("BOGUS");
  });
});

describe("formatQuantity", () => {
  it("appends the unit when the product has one", () => {
    expect(formatQuantity(3, "kg")).toBe("3 kg");
  });

  it("shows the bare number when it has none", () => {
    expect(formatQuantity(3, null)).toBe("3");
    expect(formatQuantity(3, undefined)).toBe("3");
    expect(formatQuantity(3, "  ")).toBe("3");
  });

  it("has nothing to show without a quantity", () => {
    expect(formatQuantity(null, "kg")).toBe("");
    expect(formatQuantity(undefined, "kg")).toBe("");
  });

  it("drops the column padding a piece never asked for", () => {
    expect(formatQuantity("1.000", "pcs", 1)).toBe("1 pcs");
  });

  it("keeps the places the unit allows", () => {
    expect(formatQuantity("1.500", "kg", "0.001000")).toBe("1.5 kg");
    expect(formatQuantity("0.001", "g", "0.001000")).toBe("0.001 g");
  });
});

describe("formatQuantityValue", () => {
  it("drops the padding a unit counted in whole pieces never asked for", () => {
    // numeric(10,3) says "1.000"; the unit says 1.
    expect(formatQuantityValue("1.000", 1)).toBe("1");
    expect(formatQuantityValue("1.500", "0.001000")).toBe("1.5");
  });

  it("never hides a fraction the record holds behind the unit's step", () => {
    // A pack of rice cooked down by 100 g is 0.9 pack: Stock, Movements and
    // the list totals said 0.9 while the Products list said "1 pack".
    expect(formatQuantityValue("0.900", "1.000000")).toBe("0.9");
    expect(formatQuantityValue("2.400", "1")).toBe("2.4");
    expect(formatQuantityValue("0.125", "0.01")).toBe("0.125");
  });

  it("with a unit, keeps no more places than the quantity columns store", () => {
    // A product of two amounts carries float noise past the third place.
    expect(formatQuantityValue("1.234567", "0.010000")).toBe("1.235");
    expect(formatQuantityValue(0.1 * 3, "0.001")).toBe("0.3");
  });

  it("without a unit it strips padding and invents no precision", () => {
    expect(formatQuantityValue("1.000")).toBe("1");
    expect(formatQuantityValue("1.500")).toBe("1.5");
    expect(formatQuantityValue("0.125")).toBe("0.125");
  });

  it("has nothing to say about a value that is not a number", () => {
    expect(formatQuantityValue(null, 1)).toBe("");
    expect(formatQuantityValue("", 1)).toBe("");
    expect(formatQuantityValue("n/a", 1)).toBe("n/a");
  });

  it("writes the number the way the reader's language writes it", () => {
    expect(formatQuantityValue("1.5", "0.001", "pl")).toBe("1,5");
    expect(formatQuantityValue("1.5", "0.001", "en")).toBe("1.5");
  });

  it("groups thousands, and says a number the way the other formatter says it", () => {
    // One stock, one reading: the maker screens went through this formatter
    // and printed "12345,6" where the documents said "12 345,6".
    expect(formatQuantityValue("12345.600", "0.1", "pl")).toBe("12\u00a0345,6");
    expect(formatQuantityValue("12345.600", "0.1", "en")).toBe("12,345.6");
    expect(formatQuantityValue("12345.600", "0.1", "pl")).toBe(
      formatQuantityLocale("12345.6", undefined, "pl"),
    );
  });
});

describe("decimalsAllowedBy", () => {
  it("counts the places off the step, not off the column", () => {
    expect(decimalsAllowedBy("1.000000")).toBe(0);
    expect(decimalsAllowedBy("0.001000")).toBe(3);
    expect(decimalsAllowedBy(0.01)).toBe(2);
  });

  it("treats an unknown step as whole units", () => {
    expect(decimalsAllowedBy(null)).toBe(0);
    expect(decimalsAllowedBy("abc")).toBe(0);
  });
});

describe("todayIso", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // 00:30 local on 15 Aug 2026 — 22:30 UTC on the 14th for a CEST user
    vi.setSystemTime(new Date(2026, 7, 15, 0, 30));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reads the local calendar day, not the UTC one", () => {
    // The old implementation went through toISOString(), so between midnight
    // and the UTC offset it dated exports — and prefilled form dates — a day
    // early.
    expect(todayIso()).toBe("2026-08-15");
  });

  it("is what the export filename uses", () => {
    expect(getTodayFilename()).toBe(todayIso());
  });
});

describe("formatNumberLocale — screen numbers speak the reader's mark", () => {
  it("writes the comma a Polish reader reads, where toFixed wrote a dot", () => {
    expect(formatNumberLocale(0.9, 1, "pl")).toBe("0,9");
    expect(formatNumberLocale(30, 1, "pl")).toBe("30,0");
  });

  it("keeps the dot in English", () => {
    expect(formatNumberLocale(0.9, 1, "en")).toBe("0.9");
  });

  it("keeps the places toFixed kept, even the trailing zeros", () => {
    expect(formatNumberLocale(2, 3, "pl")).toBe("2,000");
    expect(formatNumberLocale(0.125, 3, "en")).toBe("0.125");
  });

  it("reads a wire string the way it reads a number", () => {
    // decimals are fixed, so a string read with 2 places keeps the two
    // places — "1234.5" is shown as "1234,50", the same shape toFixed(2) gave.
    expect(formatNumberLocale("1234.5", 2, "pl")).toBe("1234,50");
  });

  it("answers an em dash for what has no number", () => {
    expect(formatNumberLocale(null, 1)).toBe("\u2014");
    expect(formatNumberLocale(undefined, 1)).toBe("\u2014");
    expect(formatNumberLocale(NaN, 1)).toBe("\u2014");
    expect(formatNumberLocale("n/a", 1)).toBe("\u2014");
  });
});

describe("formatPercentLocale — the percent speaks the reader's mark", () => {
  it("writes 30,5% where toFixed wrote 30.5%", () => {
    expect(formatPercentLocale(30.5, 1, "pl")).toBe("30,5%");
    expect(formatPercentLocale("30.00", 1, "pl")).toBe("30,0%");
  });

  it("keeps the dot in English, and a written figure keeps its digits", () => {
    expect(formatPercentLocale(30.5, 1, "en")).toBe("30.5%");
    // A string is the figure as written — "42.4" is a rate somebody typed,
    // and printing "42%" loses the digit they wrote.
    expect(formatPercentLocale("42.4", 0, "en")).toBe("42.4%");
  });

  it("keeps the digits a fractional rate carries instead of rounding one away", () => {
    // 20.75 read as "20,8%" is a different tax rate than the one on the wire.
    // The wire's Decimal arrives as a string, and the padding of "20.750" is
    // the column's, not the value's.
    expect(formatPercentLocale("20.75", 1, "pl")).toBe("20,75%");
    expect(formatPercentLocale("20.75", 1, "en")).toBe("20.75%");
    expect(formatPercentLocale("20.750", 1, "pl")).toBe("20,75%");
  });

  it("holds a computed percent at the caller's count, not a float's", () => {
    // 100/3 carries fifteen decimals of binary noise; printing "33,3333%"
    // invented a precision the division never had. A number has no written
    // form left, so the places are the ones the caller counted.
    expect(formatPercentLocale(100 / 3, 0, "en")).toBe("33%");
    expect(formatPercentLocale(100 / 3, 1, "pl")).toBe("33,3%");
  });

  it("does not grow a small value through rounding", () => {
    // 0.05 rounded to one place read "0,1%" — twice the waste it measured.
    expect(formatPercentLocale(0.05, 1, "pl")).toBe("0,05%");
    expect(formatPercentLocale(0.05, 0, "pl")).toBe("0,05%");
  });

  it("keeps a written value non-zero past the place cap", () => {
    // 0.00001 written with five places rounded to "0,0%" at the four-place
    // cap — "0%" would say there is nothing there, which is a different claim.
    expect(formatPercentLocale("0.00001", 1, "pl")).toBe("0,00001%");
  });

  it("widens a computed percent to its first significant digit, not to eight places", () => {
    // 100/3000 printed "0,03333333%" where it used to read "0%": a number has
    // no written digits to follow, so the guard that keeps it non-zero stops
    // at the first one that is not.
    expect(formatPercentLocale(100 / 3000, 0, "pl")).toBe("0,03%");
    expect(formatPercentLocale(100 / 3000, 1, "en")).toBe("0.03%");
    expect(formatPercentLocale(0.00007, 0, "en")).toBe("0.00007%");
  });

  it("does not throw when more places are asked for than the cap allows", () => {
    // minimumFractionDigits above maximumFractionDigits is a RangeError; the
    // request is held to the same four places the rest of the formatter is.
    expect(() => formatPercentLocale(23, 5, "pl")).not.toThrow();
    expect(formatPercentLocale(23, 5, "pl")).toBe("23,0000%");
    expect(formatPercentLocale("23.123456", 6, "en")).toBe("23.1235%");
    // The cap is a bound, not a cliff: 4 is still fine.
    expect(formatPercentLocale(23, 4, "pl")).toBe("23,0000%");
  });

  it("keeps the shape a whole rate was asked for", () => {
    expect(formatPercentLocale(23, 1, "pl")).toBe("23,0%");
  });

  it("gives the French percent sign its space", () => {
    expect(formatPercentLocale(30, 0, "fr")).toMatch(/^30\s%$/);
  });

  it("answers an em dash for what has no number", () => {
    expect(formatPercentLocale(null, 0)).toBe("\u2014");
    expect(formatPercentLocale("n/a", 0)).toBe("\u2014");
  });
});

describe("formatQuantityLocale — the caller's own decimal cap", () => {
  it("caps at the places the caller counts in", () => {
    expect(formatQuantityLocale("1.234", 1, "pl")).toBe("1,2");
  });

  it("still trims padding, and still allows four places by default", () => {
    expect(formatQuantityLocale("2.500", 3, "pl")).toBe("2,5");
    expect(formatQuantityLocale("0.1666", undefined, "pl")).toBe("0,1666");
  });
});

describe("formatBytes — a size is a number a reader reads", () => {
  const original = i18next.language;
  beforeEach(async () => {
    await i18next.changeLanguage("pl");
  });
  afterEach(async () => {
    await i18next.changeLanguage(original || "en");
  });

  it("writes the comma on a Polish screen", () => {
    expect(formatBytes(1536)).toBe("1,5 KB");
    expect(formatBytes(2 * 1024 * 1024)).toBe("2,0 MB");
  });
});

describe("formatDecimalQty", () => {
  it("drops the scale padding numeric columns serialize with", () => {
    expect(formatDecimalQty("12.0000")).toBe("12");
    expect(formatDecimalQty("1.5000")).toBe("1.5");
    expect(formatDecimalQty("7.50")).toBe("7.5");
    expect(formatDecimalQty("10.00")).toBe("10");
    expect(formatDecimalQty("0.0000")).toBe("0");
  });

  it("keeps digits the user actually entered", () => {
    expect(formatDecimalQty("0.0250")).toBe("0.025");
    expect(formatDecimalQty("12")).toBe("12");
    expect(formatDecimalQty(2.5)).toBe("2.5");
    expect(formatDecimalQty("-3.100")).toBe("-3.1");
  });

  it("rounds a division tail instead of printing 22 digits of it", () => {
    expect(formatDecimalQty("0.1666666666666666666666666667")).toBe("0.1667");
    expect(formatDecimalQty("2.00005")).toBe("2");
    expect(formatDecimalQty("0.000000125")).toBe("0.00000012");
  });

  it("passes through empty and non-numeric input untouched", () => {
    expect(formatDecimalQty(null)).toBe("");
    expect(formatDecimalQty(undefined)).toBe("");
    expect(formatDecimalQty("")).toBe("");
    expect(formatDecimalQty("n/a")).toBe("n/a");
  });
});
