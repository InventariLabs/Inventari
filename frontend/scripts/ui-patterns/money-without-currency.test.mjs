import { describe, expect, it } from "vitest";
import moneyWithoutCurrency from "./money-without-currency.mjs";

const file = (text, path = "modules/things/ThingPage.tsx") => [{ path, text }];

describe("money-without-currency", () => {
  it("flags formatMoney called with the amount alone", () => {
    const { considered, findings } = moneyWithoutCurrency.run(
      file(`const a = 1;
const s = formatMoney(row.total);`),
    );

    expect(considered).toBe(1);
    expect(findings).toEqual(["modules/things/ThingPage.tsx:2"]);
  });

  it("flags a literal undefined or null currency", () => {
    const { findings } = moneyWithoutCurrency.run(
      file(`formatMoney(a, undefined, "pl");
formatMoney(b, null);`),
    );

    expect(findings).toEqual([
      "modules/things/ThingPage.tsx:1",
      "modules/things/ThingPage.tsx:2",
    ]);
  });

  it("accepts a call that passes a currency, even an expression", () => {
    const { findings } = moneyWithoutCurrency.run(
      file(`formatMoney(a, "PLN", "pl");
formatMoney(b, currency ?? orgCurrency, locale);`),
    );

    expect(findings).toEqual([]);
  });

  it("counts only top-level arguments, not commas inside nested brackets", () => {
    const { findings } = moneyWithoutCurrency.run(
      file(`formatMoney(pick(a, b));
formatMoney({ x: 1, y: 2 });
formatMoney(sum([1, 2], 3), "EUR");`),
    );

    expect(findings).toEqual([
      "modules/things/ThingPage.tsx:1",
      "modules/things/ThingPage.tsx:2",
    ]);
  });

  it("ignores a comma inside a string argument", () => {
    const { findings } = moneyWithoutCurrency.run(
      file(`formatMoney("1,5");`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:1"]);
  });

  it("finds a multi-line call at the line of its name", () => {
    const { findings } = moneyWithoutCurrency.run(
      file(`const s = formatMoney(
  row.total
);`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:1"]);
  });

  it("ignores calls in comments and the money() hook form", () => {
    const { findings } = moneyWithoutCurrency.run(
      file(`// formatMoney(x)
/* formatMoney(y) */
const s = money(row.total);
const t = formatMoney(z, "PLN", "pl");`),
    );

    expect(findings).toEqual([]);
  });

  it("does not consider files that never call formatMoney", () => {
    const { considered, findings } = moneyWithoutCurrency.run(
      file(`const s = money(1);`),
    );

    expect(considered).toBe(0);
    expect(findings).toEqual([]);
  });
});
