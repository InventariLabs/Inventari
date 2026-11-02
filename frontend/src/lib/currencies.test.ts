import { describe, expect, it } from "vitest";
import { COUNTRY_CODES } from "./countries";
import { CURRENCY_BY_COUNTRY, CURRENCY_CODES } from "./currencies";

describe("CURRENCY_BY_COUNTRY", () => {
  it("names a currency the currency select offers for every country the country select offers", () => {
    for (const country of COUNTRY_CODES) {
      expect(CURRENCY_CODES, country).toContain(CURRENCY_BY_COUNTRY[country]);
    }
  });
});
