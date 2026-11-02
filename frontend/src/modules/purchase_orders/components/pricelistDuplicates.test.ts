import { describe, expect, it } from "vitest";
import { findDuplicates } from "./pricelistDuplicates";
import type { PartnerPricelist } from "../api/pricelist";

const entry = (
  id: string,
  overrides: Partial<PartnerPricelist> = {},
): PartnerPricelist => ({
  id,
  organization_id: "o1",
  partner_id: "p1",
  product_template_id: "t1",
  product_name: "Salted crisps",
  unit_price: "29.85",
  currency: "PLN",
  uom_id: null,
  min_quantity: "1",
  valid_from: "2026-01-01",
  valid_to: null,
  notes: null,
  created_at: null,
  updated_at: null,
  ...overrides,
});

describe("findDuplicates", () => {
  it("names the one an order actually reads", () => {
    // Measured: one product at one supplier, PLN 29.85 and PLN 62.62, both
    // from 2026-01-01, both open-ended, both min quantity 1. The query orders
    // by price, so the buyer who corrected 62.62 kept getting 29.85.
    const verdict = findDuplicates([
      entry("cheap", { unit_price: "29.85" }),
      entry("dear", { unit_price: "62.62" }),
    ]);

    expect([...verdict.effective]).toEqual(["cheap"]);
    expect([...verdict.shadowed]).toEqual(["dear"]);
  });

  it("says nothing about entries that answer different questions", () => {
    const verdict = findDuplicates([
      entry("a"),
      entry("b", { min_quantity: "100" }),
      entry("c", { valid_from: "2026-06-01" }),
      entry("d", { product_template_id: "t2" }),
      entry("e", { valid_to: "2026-03-01" }),
    ]);

    expect(verdict.effective.size).toBe(0);
    expect(verdict.shadowed.size).toBe(0);
  });

  it("treats an absent minimum quantity as its own tier", () => {
    const verdict = findDuplicates([
      entry("none", { min_quantity: null, unit_price: "10" }),
      entry("one", { min_quantity: "1", unit_price: "20" }),
    ]);

    expect(verdict.shadowed.size).toBe(0);
  });

  it("marks every loser when three rows collide", () => {
    const verdict = findDuplicates([
      entry("a", { unit_price: "50" }),
      entry("b", { unit_price: "30" }),
      entry("c", { unit_price: "40" }),
    ]);

    expect([...verdict.effective]).toEqual(["b"]);
    expect([...verdict.shadowed].sort()).toEqual(["a", "c"]);
  });
});
