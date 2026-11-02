import { describe, expect, it } from "vitest";
import { locationChoiceOf } from "./locationChoices";

describe("locationChoiceOf", () => {
  it("keeps the code, the way to the place and whether anything stands below it", () => {
    expect(
      locationChoiceOf({
        id: "shelf",
        name: "Top",
        full_path: "Warehouse → Fridge A → Top",
        short_code: "A-01",
        is_leaf: true,
      }),
    ).toEqual({
      id: "shelf",
      path: "Warehouse › Fridge A › Top",
      name: "Top",
      parentPath: "Warehouse › Fridge A",
      code: "A-01",
      leaf: true,
    });
  });

  it("has no parent path for a place at the top and no code for one without a label", () => {
    expect(
      locationChoiceOf({
        id: "wh",
        name: "Warehouse",
        full_path: null,
        short_code: null,
        is_leaf: false,
      }),
    ).toEqual({
      id: "wh",
      path: "Warehouse",
      name: "Warehouse",
      parentPath: undefined,
      code: null,
      leaf: false,
    });
  });
});
