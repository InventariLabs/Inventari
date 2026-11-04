import { describe, it, expect } from "vitest";
import type { TFunction } from "i18next";
import type { Item, LowStockProduct } from "@/types";
import { partialPackage } from "@/utils/partialPackage";
import { toAttentionItems } from "@/modules/inventory/components/dashboard/attentionItems";
import type { AttentionGroup } from "@/modules/inventory/hooks/useDashboardAttention";

// The keys are echoed with their values, so the test reads what the row says
// without depending on a locale file.
const t = ((key: string, opts?: Record<string, string>) =>
  `${key}${opts ? ` ${JSON.stringify(opts)}` : ""}`) as unknown as TFunction;

const none = () => null;

function product(over: Partial<LowStockProduct>): LowStockProduct {
  return {
    template_id: "t-1",
    name: "Spaghetti",
    on_hand: 0,
    minimum: 1,
    item_id: "i-1",
    uom_symbol: null,
    ...over,
  };
}

describe("toAttentionItems — dated records", () => {
  it("links to the record's date, which is why the row is on the card", () => {
    const record = {
      id: "i-7",
      name: "Cottage Cheese",
      location_id: "l-1",
      expiry_date: "2026-10-29",
      quantity: 10,
    } as unknown as Item;
    const [row] = toAttentionItems(
      [{ key: "g-1", kind: "expired", items: [record] }] as AttentionGroup[],
      new Map(),
      [],
      t,
      none,
    );
    expect(row.href).toBe("/inventory/items?open=i-7&at=expiry");
  });
});

describe("toAttentionItems — short products", () => {
  it("says a used-up product has none left, against its minimum", () => {
    const [row] = toAttentionItems([], new Map(), [product({})], t, none);
    expect(row).toMatchObject({
      id: "low:t-1",
      severity: "low",
      title: "Spaghetti",
      href: "/inventory/items/i-1",
    });
    expect(row.reason).toContain("dashboard.attention.out");
    expect(row.reason).toContain('"minimum":"1"');
    // Where its last record went is bookkeeping, not part of the answer.
    expect(row.where).toBeUndefined();
  });

  it("gives what is on the shelf against the minimum for a product in stock", () => {
    const [row] = toAttentionItems(
      [],
      new Map(),
      [product({ on_hand: 3, minimum: 10, name: "Rice" })],
      t,
      none,
    );
    expect(row.reason).toContain("dashboard.attention.low");
    expect(row.reason).toContain('"quantity":"3"');
    expect(row.reason).toContain('"minimum":"10"');
  });

  it("opens the product's own page, used up or not", () => {
    const [row] = toAttentionItems(
      [],
      new Map(),
      [product({ on_hand: 0, item_id: "i-9" })],
      t,
      none,
    );
    expect(row.href).toBe("/inventory/items/i-9");
  });

  it("falls back to the list for a product with no record", () => {
    const [row] = toAttentionItems(
      [],
      new Map(),
      [product({ item_id: null })],
      t,
      none,
    );
    expect(row.href).toBe("/inventory/items");
  });
});

describe("toAttentionItems — a product held as two records", () => {
  // Cooking 500 ml out of three 1 l cartons leaves two records of one
  // product with the same expiry: both counted in pieces, 2 and 0.5, on a
  // card that says a piece holds 1 l.
  const record = (id: string, quantity: string) =>
    ({
      id,
      name: "Milk 3.2% 1 l",
      expiry_date: "2026-10-31",
      location_id: "loc-1",
      quantity,
      uom: { symbol: "pcs", category_name: "Unit" },
    }) as unknown as Item;
  const group = (item: Item): AttentionGroup => ({
    key: `expiring:${item.id}`,
    kind: "expiring",
    items: [item],
  });
  const litre = (item: Item) =>
    partialPackage({
      quantity: item.quantity,
      uom: item.uom,
      pieceMeasure: { value: 1, symbol: "l" },
    });

  it("tells the two rows apart, the half carton as the list reads it", () => {
    const rows = toAttentionItems(
      [group(record("a", "2.0000")), group(record("b", "0.5000"))],
      new Map(),
      [],
      t,
      litre,
    );
    expect(rows).toHaveLength(2);
    expect(rows[0].title).toBe(rows[1].title);
    expect(rows[0].reason).not.toBe(rows[1].reason);
    expect(rows[0].reason).toContain('"quantity":"2 ');
    expect(rows[1].reason).toContain("common:partialPackage.left");
    expect(rows[1].reason).not.toContain("pcs");
  });
});
