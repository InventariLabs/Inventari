import { describe, expect, it } from "vitest";
import { computeLineValueWithTax } from "./poLineCalc";

describe("computeLineValueWithTax", () => {
  it("returns empty string for invalid price", () => {
    expect(computeLineValueWithTax(5, "", "23")).toBe("");
    expect(computeLineValueWithTax(5, "abc", "23")).toBe("");
    expect(computeLineValueWithTax(5, "-10", "23")).toBe("");
  });

  it("calculates subtotal without tax", () => {
    expect(computeLineValueWithTax(10, "5.00", "")).toBe("50.00");
    expect(computeLineValueWithTax(3, "10.00", "0")).toBe("30.00");
  });

  it("calculates subtotal with tax", () => {
    expect(computeLineValueWithTax(10, "100.00", "23")).toBe("1230.00");
    expect(computeLineValueWithTax(2, "50.00", "8")).toBe("108.00");
  });

  it("handles zero quantity", () => {
    expect(computeLineValueWithTax(0, "10.00", "23")).toBe("0.00");
  });

  it("handles fractional values", () => {
    expect(computeLineValueWithTax(3, "33.33", "8")).toBe("107.99");
  });

  it("returns empty for negative price", () => {
    expect(computeLineValueWithTax(5, "-1", "23")).toBe("");
  });
});
