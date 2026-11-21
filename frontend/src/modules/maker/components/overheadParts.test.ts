import { describe, it, expect } from "vitest";
import { overheadParts } from "./overheadParts";
import type { CostBreakdownResponse } from "@/modules/maker/types/maker";

const base: CostBreakdownResponse = {
  output_template_id: "tpl",
  planned_qty: "10",
  total_cost: "252.80",
  ingredients_cost: "112.80",
  fixed_cost: "20.00",
  labour_cost: "120.00",
  recipe_state: "has_lines",
  recipe_id: "r",
  entries: [],
  missing_cost_lines: [],
};

describe("overheadParts", () => {
  it("names fixed costs and labour with their share of the whole total", () => {
    expect(overheadParts(base)).toEqual([
      { kind: "fixed", cost: "20.00", percentage: "7.91" },
      { kind: "labour", cost: "120.00", percentage: "47.47" },
    ]);
  });

  it("leaves out a part the formula does not have", () => {
    const parts = overheadParts({
      ...base,
      fixed_cost: "0.00",
      total_cost: "232.80",
    });
    expect(parts.map((p) => p.kind)).toEqual(["labour"]);
  });
});
