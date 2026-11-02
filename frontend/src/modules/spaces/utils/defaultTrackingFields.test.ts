import { describe, it, expect } from "vitest";
import { defaultTrackingFieldsForLocation } from "./defaultTrackingFields";

describe("defaultTrackingFieldsForLocation", () => {
  it("returns an empty list when location name is empty", () => {
    expect(defaultTrackingFieldsForLocation("")).toEqual([]);
    expect(defaultTrackingFieldsForLocation("   ")).toEqual([]);
  });

  it("returns an empty list for any non-empty name (no name-based heuristic)", () => {
    // Contract: storage is vertical-agnostic. We no longer infer
    // freeze_date from names like "Freezer" — that's a category-level decision.
    // The wizard's neutral defaults are the same regardless of the typed name.
    expect(defaultTrackingFieldsForLocation("Freezer")).toEqual([]);
    expect(defaultTrackingFieldsForLocation("Zamrażarka")).toEqual([]);
    expect(defaultTrackingFieldsForLocation("Fridge")).toEqual([]);
    expect(defaultTrackingFieldsForLocation("Lodówka")).toEqual([]);
    expect(defaultTrackingFieldsForLocation("Pantry")).toEqual([]);
    expect(defaultTrackingFieldsForLocation("Cellar")).toEqual([]);
    expect(defaultTrackingFieldsForLocation("Garage")).toEqual([]);
  });

  it("never returns food/equipment-biased defaults", () => {
    const forbidden = [
      "freeze_date",
      "expiry_date",
      "production_date",
      "brand",
      "serial_number",
      "manufacturer",
      "model",
      "equipment_status",
    ];
    for (const name of [
      "Freezer",
      "Fridge",
      "Pantry",
      "Equipment",
      "Library",
    ]) {
      const defaults = defaultTrackingFieldsForLocation(name);
      for (const forbiddenKey of forbidden) {
        expect(defaults).not.toContain(forbiddenKey);
      }
    }
  });

  it("returns a frozen (readonly) array — callers must not mutate it", () => {
    const a = defaultTrackingFieldsForLocation("Any");
    expect(Object.isFrozen(a)).toBe(true);
  });
});
