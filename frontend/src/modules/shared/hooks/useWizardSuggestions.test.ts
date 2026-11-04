import { describe, it, expect } from "vitest";
import { nameAfterChip } from "./useWizardSuggestions";

const chips = ["Rack", "Shelf", "Drawer"];

describe("nameAfterChip", () => {
  it("fills an empty field", () => {
    expect(nameAfterChip("", "Rack", chips)).toBe("Rack");
    expect(nameAfterChip("  ", "Rack", chips)).toBe("Rack");
  });

  it("swaps one chip for another", () => {
    expect(nameAfterChip("Shelf", "Rack", chips)).toBe("Rack");
  });

  it("completes a half-typed word", () => {
    expect(nameAfterChip("Ra", "Rack", chips)).toBe("Rack");
  });

  it("keeps a name that was typed", () => {
    expect(nameAfterChip("Rack A", "Rack", chips)).toBe("Rack A");
    expect(nameAfterChip("Back room", "Rack", chips)).toBe("Back room");
  });
});
