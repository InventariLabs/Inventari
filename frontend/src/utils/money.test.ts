import { describe, it, expect } from "vitest";
import { amountsByRate, lineAmounts, roundHalfUp, totalAmounts } from "./money";

describe("roundHalfUp", () => {
  it("sends a half away from zero, where toFixed sends it down", () => {
    // Not every half survives the binary representation: 2.675 is stored a
    // hair under it, so toFixed sends it down while the backend stores 2.68.
    expect((2.675).toFixed(2)).toBe("2.67");
    expect(roundHalfUp(2.675)).toBe(2.68);
    expect((1.005).toFixed(2)).toBe("1.00");
    expect(roundHalfUp(1.005)).toBe(1.01);
  });

  it("rounds an ordinary number the ordinary way", () => {
    expect(roundHalfUp(12.344)).toBe(12.34);
    expect(roundHalfUp(12.345)).toBe(12.35);
  });

  it("keeps the sign", () => {
    expect(roundHalfUp(-2.675)).toBe(-2.68);
  });
});

describe("lineAmounts", () => {
  it("prints a net and a tax that add up to the printed gross", () => {
    // 3 x 1.665 at 23%: net 4.995 -> 5.00, tax 1.14885 -> 1.15.
    const { net, tax, gross } = lineAmounts(3, "1.665", "23");
    expect(net).toBe(5.0);
    expect(tax).toBe(1.15);
    expect(gross).toBe(6.15);
    expect(net + tax).toBe(gross);
  });

  it("differs from rounding the combined figure, which is the point", () => {
    // The old rule: (4.995 * 1.23).toFixed(2) === "6.14".
    expect((3 * 1.665 * 1.23).toFixed(2)).toBe("6.14");
    expect(lineAmounts(3, "1.665", "23").gross).toBe(6.15);
  });

  it("treats a missing price or rate as nothing, not as an error", () => {
    expect(lineAmounts(2, null, null)).toEqual({ net: 0, tax: 0, gross: 0 });
    expect(lineAmounts("4", "2.50", null).net).toBe(10);
  });
});

describe("totalAmounts", () => {
  it("sums the rounded lines, not the raw ones", () => {
    const totals = totalAmounts([
      { quantity: 3, unit_price: "1.665", tax_rate: "23" },
      { quantity: 3, unit_price: "1.665", tax_rate: "23" },
    ]);
    expect(totals.net).toBe(10.0);
    expect(totals.tax).toBe(2.3);
    expect(totals.gross).toBe(12.3);
  });

  it("ignores nothing and adds an unpriced line as zero", () => {
    const totals = totalAmounts([
      { quantity: 2, unit_price: "10", tax_rate: null },
      { quantity: 5, unit_price: null, tax_rate: "23" },
    ]);
    expect(totals.net).toBe(20);
    expect(totals.tax).toBe(0);
  });
});

describe("amountsByRate", () => {
  it("sums each rate apart, highest first", () => {
    expect(
      amountsByRate([
        { tax_rate: "7.00", line_value: "10.00", line_tax: "0.70" },
        { tax_rate: "19.00", line_value: "100.00", line_tax: "19.00" },
        { tax_rate: "7", line_value: "5.00", line_tax: "0.35" },
      ]),
    ).toEqual([
      { rate: 19, net: 100, tax: 19, gross: 119 },
      { rate: 7, net: 15, tax: 1.05, gross: 16.05 },
    ]);
  });

  it("leaves untaxed and unpriced lines out, and keeps a zero rate", () => {
    expect(
      amountsByRate([
        { tax_rate: null, line_value: "10.00", line_tax: null },
        { tax_rate: "7.00", line_value: null, line_tax: null },
        { tax_rate: "0.00", line_value: "4.20", line_tax: "0.00" },
      ]),
    ).toEqual([{ rate: 0, net: 4.2, tax: 0, gross: 4.2 }]);
  });
});
