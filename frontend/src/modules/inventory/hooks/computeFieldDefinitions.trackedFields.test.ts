import { describe, it, expect } from "vitest";
import { computeFieldDefinitions } from "./computeFieldDefinitions";
import {
  makeLocationField,
  makeStorageSummary,
} from "@/test/factories/storage";
import type { StorageLocationSummary } from "@/types";

const baseContext = {
  selectedCategory: undefined,
  uomCategoryName: null,
} as const;

const visibleKeys = (storage: StorageLocationSummary) =>
  computeFieldDefinitions({ ...baseContext, selectedStorage: storage })
    .filter((f) => f.visible)
    .map((f) => f.key);

/**
 * A location names the product fields it tracks in its own words: the toggle
 * "Notes" is the product's description and "Price" its purchase price, while
 * Product code and Shelf / position already carry the product's own key. The
 * form shows the fields those toggles ask for — it must not read the two
 * names as fields of their own and hide the real ones instead.
 */
describe("computeFieldDefinitions — the tracked fields Notes and Price", () => {
  it("shows the description and the purchase price where the location tracks them", () => {
    const shelf = makeStorageSummary({ context_schema: ["notes", "price"] });

    expect(visibleKeys(shelf)).toEqual(
      expect.arrayContaining(["description", "purchase_price"]),
    );
  });

  it("keeps hiding the fields the location does not track", () => {
    const shelf = makeStorageSummary({ context_schema: ["notes", "price"] });

    expect(visibleKeys(shelf)).not.toContain("shelf_location");
  });

  it("takes the product's own key for the same field as well", () => {
    const shelf = makeStorageSummary({
      context_schema: ["description", "purchase_price"],
    });

    expect(visibleKeys(shelf)).toEqual(
      expect.arrayContaining(["description", "purchase_price"]),
    );
  });

  it("reads a tracked field set on a level above the same way", () => {
    const shelf = makeStorageSummary({
      inherited_context_schema: [
        { key: "price", from_id: "r1", from_name: "Rack" },
      ],
    });

    expect(visibleKeys(shelf)).toContain("purchase_price");
  });

  it("still lets the storage's own field definitions add fields of their own", () => {
    const shelf = makeStorageSummary({
      context_schema: ["notes"],
      field_definitions: [makeLocationField("batch", { label: "Batch" })],
    });

    expect(visibleKeys(shelf)).toEqual(
      expect.arrayContaining(["description", "batch"]),
    );
  });
});

/**
 * The SKU is the product's own stock-keeping number, and the add and edit
 * forms are where it is set. A location that lists the fields it tracks
 * decides for itself, like for the product code.
 */
describe("computeFieldDefinitions — the SKU", () => {
  it("is offered where the location limits nothing", () => {
    expect(visibleKeys(makeStorageSummary({ context_schema: [] }))).toContain(
      "sku",
    );
  });

  it("is offered where the location tracks it", () => {
    const shelf = makeStorageSummary({ context_schema: ["sku"] });

    expect(visibleKeys(shelf)).toContain("sku");
  });

  it("is left out where the location tracks other fields only", () => {
    const shelf = makeStorageSummary({ context_schema: ["barcode"] });

    expect(visibleKeys(shelf)).not.toContain("sku");
  });
});
