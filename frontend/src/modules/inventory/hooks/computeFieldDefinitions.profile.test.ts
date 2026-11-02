import { describe, it, expect } from "vitest";
import { computeFieldDefinitions } from "./computeFieldDefinitions";
import { buildSubmissionPayload } from "./buildSubmissionPayload";
import type { StorageLocationSummary } from "@/types";

const baseContext = {
  selectedCategory: undefined,
  selectedStorage: undefined,
  uomCategoryName: null,
} as const;

/**
 * The purchase price feeds one thing: the stock value the stats module's
 * "Show inventory value" switch puts on screen. Where that switch is off the
 * record overview, the list footer and the stock-as-of report hide the value,
 * so the form hides the field too — a price typed there feeds nothing, and a
 * stored one would show on the edit form the overview has just hidden. Where
 * the switch is on the field is offered whatever the profile: a home pantry
 * whose admin turned the value back on can type the price that feeds it.
 */
describe("computeFieldDefinitions — the purchase price follows the inventory-value switch", () => {
  const priceVisible = (fields: ReturnType<typeof computeFieldDefinitions>) =>
    fields.find((f) => f.key === "purchase_price")?.visible;

  it("hides purchase_price where the inventory value is not shown", () => {
    expect(
      priceVisible(
        computeFieldDefinitions({ ...baseContext, showInventoryValue: false }),
      ),
    ).toBe(false);
  });

  it("offers purchase_price where the value is shown, and by default", () => {
    expect(
      priceVisible(
        computeFieldDefinitions({ ...baseContext, showInventoryValue: true }),
      ),
    ).toBe(true);
    expect(priceVisible(computeFieldDefinitions(baseContext))).toBe(true);
  });

  it("keeps it hidden whatever the storage's field list says", () => {
    const storage = {
      id: "sl-1",
      name: "Shop floor",
      context_schema: ["purchase_price"],
    } as unknown as StorageLocationSummary;
    expect(
      priceVisible(
        computeFieldDefinitions({
          ...baseContext,
          selectedStorage: storage,
          showInventoryValue: false,
        }),
      ),
    ).toBe(false);
  });

  it("leaves every other field the switch has no opinion about alone", () => {
    const shown = computeFieldDefinitions(baseContext);
    const hidden = computeFieldDefinitions({
      ...baseContext,
      showInventoryValue: false,
    });
    const visibilityByKey = (fields: typeof shown) =>
      Object.fromEntries(fields.map((f) => [f.key, f.visible]));
    const before = visibilityByKey(shown);
    const after = visibilityByKey(hidden);
    for (const key of Object.keys(before)) {
      if (key === "purchase_price") continue;
      expect(after[key]).toBe(before[key]);
    }
  });

  it("submits a filled purchase price only where the field is visible", () => {
    // The payload builder honours the same definitions the form draws: a
    // hidden field leaves the submission, so an edit leaves the stored price
    // as it was instead of clearing it.
    const formData = { name: "Milk", quantity: "1", purchase_price: "3.5" };

    const visible = buildSubmissionPayload(
      formData,
      computeFieldDefinitions(baseContext),
    );
    expect(visible.purchase_price).toBe(3.5);

    const hidden = buildSubmissionPayload(
      formData,
      computeFieldDefinitions({ ...baseContext, showInventoryValue: false }),
    );
    expect("purchase_price" in hidden).toBe(false);
  });
});

/**
 * A receiving or picking terminal finds a product by its code, and the
 * product form is where a worker gives it one. Nothing but a location that
 * lists the fields it tracks may take the field away.
 */
describe("computeFieldDefinitions — the product code", () => {
  const barcodeVisible = (fields: ReturnType<typeof computeFieldDefinitions>) =>
    fields.find((f) => f.key === "barcode")?.visible;

  it("offers the barcode field whether or not stock value is shown", () => {
    for (const showInventoryValue of [true, false]) {
      expect(
        barcodeVisible(
          computeFieldDefinitions({ ...baseContext, showInventoryValue }),
        ),
      ).toBe(true);
    }
  });

  it("offers it in a location that tracks no fields of its own", () => {
    const storage = {
      id: "sl-1",
      name: "Main warehouse",
      context_schema: [],
    } as unknown as StorageLocationSummary;
    const fields = computeFieldDefinitions({
      ...baseContext,
      selectedStorage: storage,
    });
    expect(barcodeVisible(fields)).toBe(true);
  });
});
