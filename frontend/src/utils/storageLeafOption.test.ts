import { describe, expect, it } from "vitest";

import { storageLeafLabel, storageLeafOption } from "./storageLeafOption";

const warehouse = { id: "w", name: "Main Warehouse", parent_id: null };
const cold = { id: "c", name: "Cold Storage", parent_id: "w" };
const fridge = { id: "f", name: "Fridge A - Top Shelf", parent_id: "c" };
const all = [warehouse, cold, fridge];

describe("storageLeafOption", () => {
  it("titles the row with the place itself and captions it with the path", () => {
    expect(storageLeafOption(fridge, all)).toEqual({
      id: "f",
      name: "Fridge A - Top Shelf",
      path: "Main Warehouse → Cold Storage → Fridge A - Top Shelf",
    });
  });

  it("prefers the path the backend composed", () => {
    expect(
      storageLeafOption({ ...fridge, full_path: "Elsewhere → Top" }, all).path,
    ).toBe("Elsewhere → Top");
  });

  it("leaves a root location without a caption that only repeats its name", () => {
    expect(storageLeafOption(warehouse, all)).toEqual({
      id: "w",
      name: "Main Warehouse",
      path: undefined,
    });
  });
});

describe("storageLeafLabel", () => {
  it("leads with the place's name, so a clip takes the path", () => {
    expect(
      storageLeafLabel({
        name: "Fridge A - Top Shelf",
        path: "Main Warehouse › Cold Storage › Fridge A",
      }),
    ).toBe("Fridge A - Top Shelf — Main Warehouse › Cold Storage › Fridge A");
  });

  it("is the name alone for a place at the top", () => {
    expect(storageLeafLabel({ name: "Main Warehouse" })).toBe("Main Warehouse");
  });
});
