import { describe, expect, it } from "vitest";

import {
  diffBaseline,
  findingsOf,
  rulesBroken,
  strings,
} from "./check-vocabulary.mjs";

const file = "src/i18n/locales/en/items.json";
const broken = (value, path = "a.b", f = file) => rulesBroken(f, path, value);

describe("the retired words", () => {
  it.each([
    ["My places", "place"],
    ["Add your first product to your storage", "storage"],
    ["{{count}} places", "place"],
    ["Add to warehouse", "warehouse"],
    ["Pick a room", "zone-room-spot"],
    ["How much of it is spoken for", "spoken-for"],
    ["Product taken off stock", "take-off-stock"],
    ["Deduct the ingredients", "take-off-stock"],
    ["Error while consuming", "consume-verb"],
    ["Consume 1", "consume-verb"],
    ["Add an item", "product-item"],
    ["Search articles", "product-item"],
    ["{{count}} stock entries", "record-entry"],
    ["Quantity held for an order", "held"],
    ["Relocate this product", "relocate-shift"],
    ["Shift the stock to another site", "relocate-shift"],
    ["Transfer the products to the new site", "transfer-verb"],
    ["Every transaction is listed here", "transaction"],
    ["Quantity in hand", "on-hand"],
    ["Show used up", "used-up"],
    ["Spent", "used-up"],
    ["Mark the batch as spent", "used-up"],
    ["Select a shelf", "shelf"],
    ["Goods go to the first shelf they fit", "shelf"],
    ["Choose a workspace profile", "profile"],
    ["Switch profile", "profile"],
    ["Left", "available-column"],
    ["Free stock", "available-column"],
  ])("flags %j as %s", (value, rule) => {
    expect(broken(value)).toEqual([rule]);
  });

  it.each([
    "Too many decimal places (max {{places}})",
    "Not a place inside someone else's organization",
    "The only place a line can be re-parented",
    "Create a custom role for a warehouse operator",
    "Warehouse Documents",
    "Numbered, registered warehouse documents",
    "Equipment & Warehouse",
    "e.g. LOC-001, WAREHOUSE-A-1",
    "Consumed",
    "Consumption by month",
    "Remove from stock",
    "Placeholder text and replacement",
    "Reserved",
    "Line items",
    "Add a line item",
    "Shopping list items",
    "Quantity reserved for an order",
    "Move the products to another location",
    "Storage (GB)",
    "Track food inventory and cold storage",
    "Transfer documents",
    "Create an internal transfer",
    "Stock on hand",
    "Left of the screen",
    "Freeze the column",
    "Total spent",
    "Spent on groceries this month",
    "Short shelf life: {{date}}",
    "Beverages (shelf-stable)",
    "e.g. Shelf A, rack 2 and Top Shelf",
    "My profile",
    "Save the document profile",
  ])("leaves %j alone", (value) => {
    expect(broken(value)).toEqual([]);
  });

  it("leaves the name of the warehouse module to that module", () => {
    expect(
      broken(
        "Warehouse",
        "launcher.title",
        "src/modules/warehouse/i18n/en.json",
      ),
    ).toEqual([]);
    expect(broken("Warehouse")).toEqual(["warehouse"]);
  });

  it("leaves the starter names offered for a new location alone", () => {
    expect(broken("Living room", "suggestions.zones[4]")).toEqual([]);
  });

  it("leaves a bare Shelf, the type offered for a new location, alone", () => {
    expect(broken("Shelf", "compartments[0]")).toEqual([]);
  });

  it("leaves the cost-analysis Spent column, which is money, alone", () => {
    expect(
      broken(
        "Spent",
        "costAnalysis.spent",
        "src/modules/stats/i18n/en.json",
      ),
    ).toEqual([]);
  });

  it("leaves a document profile to the warehouse module", () => {
    expect(
      broken("Save Profile", "a.b", "src/modules/warehouse/i18n/en.json"),
    ).toEqual([]);
  });

  it("lets a production run consume its ingredients", () => {
    expect(
      broken(
        "Consumes the listed ingredients",
        "a.b",
        "src/modules/maker/i18n/en.json",
      ),
    ).toEqual([]);
  });
});

describe("findingsOf", () => {
  it("keys a finding by file, path and rule, and walks arrays", () => {
    expect(
      findingsOf(file, { a: { b: ["fine", "in a place"] }, c: "Reserved" }),
    ).toEqual({ [`${file}::a.b[1]::place`]: "in a place" });
  });

  it("reads every string leaf", () => {
    expect(strings({ a: "x", b: { c: ["y"] }, d: 3 })).toEqual([
      { path: "a", value: "x" },
      { path: "b.c[0]", value: "y" },
    ]);
  });
});

describe("diffBaseline", () => {
  const key = `${file}::a::place`;

  it("shields a string the baseline holds with the same text", () => {
    expect(diffBaseline({ [key]: "a place" }, { [key]: "a place" })).toEqual({
      added: [],
      changed: [],
      fixed: [],
    });
  });

  it("fails a new string", () => {
    expect(diffBaseline({ [key]: "a place" }, {}).added).toEqual([key]);
  });

  it("fails a shielded string whose text changed and still offends", () => {
    expect(
      diffBaseline({ [key]: "another place" }, { [key]: "a place" }).changed,
    ).toEqual([key]);
  });

  it("reports a baseline entry that no longer offends", () => {
    expect(diffBaseline({}, { [key]: "a place" }).fixed).toEqual([key]);
  });
});
