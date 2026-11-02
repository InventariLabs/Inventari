import { afterAll, beforeAll, describe, expect, it } from "vitest";
import i18n from "@/i18n/config";
import { formatQuantityLocale } from "../formatters";

describe("formatQuantityLocale", () => {
  const original = i18n.language;
  beforeAll(async () => {
    await i18n.changeLanguage("en");
  });
  afterAll(async () => {
    await i18n.changeLanguage(original);
  });

  it("drops the scale the database carries", () => {
    expect(formatQuantityLocale("5.000000")).toBe("5");
  });

  it("cuts the tail of a division that never ends", () => {
    // Server-side division arrives as 22 digits around one useful number.
    expect(formatQuantityLocale("0.1666666666666666666667")).toBe("0.1667");
  });

  it("groups thousands, which String(Number(...)) never did", () => {
    expect(formatQuantityLocale("12500")).toBe("12,500");
  });

  it("keeps a value too small to survive rounding non-zero", () => {
    // "0" would say the stock is gone, which is a different claim from
    // "there is very little of it".
    expect(formatQuantityLocale("0.00002")).toBe("0.00002");
  });

  it("hands back anything that is not a number untouched", () => {
    expect(formatQuantityLocale("n/a")).toBe("n/a");
    expect(formatQuantityLocale("")).toBe("");
  });

  it("writes the number the way the reader's language does", async () => {
    // Four of the five supported languages put a comma where JavaScript's
    // own `String(Number(...))` puts a point, and none of them ever saw one.
    await i18n.changeLanguage("pl");
    expect(formatQuantityLocale("1234.5")).toBe("1234,5");
    await i18n.changeLanguage("de");
    expect(formatQuantityLocale("1234.5")).toBe("1.234,5");
    await i18n.changeLanguage("en");
  });
});
