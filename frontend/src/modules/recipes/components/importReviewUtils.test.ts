import { describe, it, expect } from "vitest";
import {
  previewToDraft,
  composeDisplayText,
  willBeSpice,
  type IngredientDraft,
} from "./importReviewUtils";
import type { Uom } from "@/types";

const baseDraft: IngredientDraft = {
  _key: 0,
  name: "black pepper",
  quantity: "1",
  uom_id: null,
  original_text: "pieprz czarny - 1 szczypta",
  group_name: "pepper",
  template_id: null,
  template_name: null,
  is_optional: false,
  is_spice_forced: false,
  allergens: [],
  original_unit_text: "szczypta",
  unread_unit: null,
  unit_display: "pinch",
  metric_quantity: "0.5",
  conversion_ratio: 0.5,
};

describe("previewToDraft", () => {
  it("keeps the unit text it could not match, so the review can name it", () => {
    const unread = previewToDraft(
      {
        name: "Soy sauce",
        quantity: 2,
        uom_id: null,
        original_unit_text: "tbsp",
      },
      0,
    );
    expect(unread.unread_unit).toBe("tbsp");
    const read = previewToDraft(
      { name: "Flour", quantity: 2, uom_id: "uom-g", original_unit_text: "g" },
      1,
    );
    expect(read.unread_unit).toBeNull();
  });

  it("keeps imported spice and allergen metadata", () => {
    const draft = previewToDraft(
      { name: "Bay leaf", quantity: 1, is_spice: true, allergens: ["mustard"] },
      0,
    );
    expect(draft.is_spice_forced).toBe(true);
    expect(draft.allergens).toEqual(["mustard"]);
  });

  it("defaults metadata omitted by older previews", () => {
    const draft = previewToDraft({ name: "Water", quantity: 100 }, 0);
    expect(draft.is_spice_forced).toBe(false);
    expect(draft.allergens).toEqual([]);
  });

  it("maps unit_display when original unit is present", () => {
    const draft = previewToDraft(
      {
        name: "black pepper",
        quantity: 0.5,
        original_quantity: 1,
        original_unit_text: "szczypta",
        unit_display: "pinch",
      },
      0,
    );
    expect(draft.original_unit_text).toBe("szczypta");
    expect(draft.unit_display).toBe("pinch");
    expect(draft.quantity).toBe("1");
    expect(draft.metric_quantity).toBe("0.5");
  });

  it("nulls unit_display for metric-only ingredients", () => {
    const draft = previewToDraft(
      { name: "parsley root", quantity: 150, unit_display: "g" },
      0,
    );
    expect(draft.original_unit_text).toBeNull();
    expect(draft.unit_display).toBeNull();
  });

  it("keeps uom_id from the import preview (round-trip)", () => {
    const draft = previewToDraft(
      {
        name: "Flour",
        quantity: 300,
        uom_id: "uom-g",
        original_unit_text: "g",
      },
      0,
    );
    expect(draft.uom_id).toBe("uom-g");
  });

  it("keeps uom_id null for unrecognized units", () => {
    const draft = previewToDraft(
      { name: "Flour", quantity: 300, uom_id: null, original_unit_text: "g" },
      0,
    );
    expect(draft.uom_id).toBeNull();
  });
});

describe("composeDisplayText", () => {
  it("composes translated line from name, quantity and translated unit", () => {
    expect(composeDisplayText(baseDraft)).toBe("black pepper - 1 pinch");
  });

  it("falls back to original unit when translation is missing", () => {
    expect(composeDisplayText({ ...baseDraft, unit_display: null })).toBe(
      "black pepper - 1 szczypta",
    );
  });

  it("reflects user edits to name and quantity", () => {
    expect(
      composeDisplayText({
        ...baseDraft,
        name: "  ground cumin ",
        quantity: "2",
      }),
    ).toBe("ground cumin - 2 pinch");
  });

  it("returns null for metric-only ingredients (structured rendering)", () => {
    expect(
      composeDisplayText({
        ...baseDraft,
        original_unit_text: null,
        unit_display: null,
      }),
    ).toBeNull();
  });

  it("returns null when name is empty", () => {
    expect(composeDisplayText({ ...baseDraft, name: "   " })).toBeNull();
  });
});

describe("willBeSpice", () => {
  const uom = (id: string, symbol: string): Uom => ({
    id,
    name: symbol,
    symbol,
    factor: "1",
    rounding: "1",
    is_reference: false,
    is_system: false,
    category_id: "cat",
  });
  const uoms = [uom("u-g", "g"), uom("u-pcs", "pcs"), uom("u-kg", "kg")];

  it("marks a small weight or volume as seasoning", () => {
    expect(willBeSpice("5", "u-g", uoms)).toBe(true);
  });

  it("leaves a larger amount of the same unit alone", () => {
    expect(willBeSpice("15", "u-g", uoms)).toBe(false);
  });

  it("never marks a piece as seasoning by amount", () => {
    // The card no longer folds one-piece ingredients under the spices, and
    // the review's chip asks the same question, so it answers the same.
    expect(willBeSpice("1", "u-pcs", uoms)).toBe(false);
  });

  it("ignores units that are neither weight nor volume", () => {
    expect(willBeSpice("0.5", "u-kg", uoms)).toBe(false);
  });

  it("answers false without a unit or a number", () => {
    expect(willBeSpice("5", null, uoms)).toBe(false);
    expect(willBeSpice("", "u-g", uoms)).toBe(false);
  });
});
