import { describe, expect, it } from "vitest";
import {
  findScannedBatch,
  lotChoicesPayload,
  shortChoices,
} from "@/modules/maker/lib/batchChoice";
import type { IngredientBatchPlan } from "@/modules/maker/types/maker";

const honey: IngredientBatchPlan = {
  template_id: "honey",
  template_name: "Honey",
  uom_symbol: "kg",
  needed: "6.0000",
  plan: [{ lot_id: "early", lot_name: "H-EARLY", quantity: "6.0000" }],
  batches: [
    { lot_id: "early", lot_name: "H-EARLY", available: "10.0000" },
    { lot_id: "late", lot_name: "H-LATE", available: "4.0000" },
  ],
};

const sugar: IngredientBatchPlan = {
  template_id: "sugar",
  template_name: "Sugar",
  uom_symbol: "kg",
  needed: "2.0000",
  // Kept outside any batch: there is no batch to name.
  plan: [{ lot_id: null, lot_name: null, quantity: "2.0000" }],
  batches: [],
};

describe("what the run is told to take", () => {
  it("takes the whole need from a chosen batch", () => {
    expect(lotChoicesPayload([honey], { honey: "late" })).toEqual([
      { template_id: "honey", lot_id: "late", quantity: "6.0000" },
    ]);
  });

  it("sends the plan the page showed when every part of it names a batch", () => {
    expect(lotChoicesPayload([honey], {})).toEqual([
      { template_id: "honey", lot_id: "early", quantity: "6.0000" },
    ]);
  });

  it("leaves stock kept without batches to the removal order", () => {
    expect(lotChoicesPayload([sugar], {})).toEqual([]);
  });

  it("sends nothing for a plan that does not cover the need", () => {
    const short = { ...honey, needed: "12.0000" };
    expect(lotChoicesPayload([short], {})).toEqual([]);
  });
});

describe("a scanned batch label", () => {
  it("picks the batch for the ingredient it belongs to, whatever the case", () => {
    expect(findScannedBatch([sugar, honey], " h-late ")).toEqual({
      templateId: "honey",
      lotId: "late",
    });
  });

  it("finds nothing for a code no ingredient has", () => {
    expect(findScannedBatch([honey], "X-1")).toBeNull();
  });
});

it("says which chosen batch cannot give the need", () => {
  expect([...shortChoices([honey], { honey: "late" })]).toEqual(["honey"]);
  expect([...shortChoices([honey], { honey: "early" })]).toEqual([]);
});
