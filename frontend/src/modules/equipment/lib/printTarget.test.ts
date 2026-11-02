import { describe, expect, it } from "vitest";
import { selectedLabelTarget } from "./printTarget";

describe("selectedLabelTarget", () => {
  const items = [
    { id: "a", label_code: "EQP-0001" },
    { id: "b", label_code: null },
    { id: "c", label_code: "EQP-0003" },
  ];

  it("sends the label codes of the selected assets that have one", () => {
    expect(selectedLabelTarget(items, new Set(["a", "b", "c"]))).toEqual({
      shortCodes: ["EQP-0001", "EQP-0003"],
    });
  });

  it("has nothing to send when no selected asset carries a label", () => {
    expect(selectedLabelTarget(items, new Set(["b"]))).toBeNull();
  });
});
