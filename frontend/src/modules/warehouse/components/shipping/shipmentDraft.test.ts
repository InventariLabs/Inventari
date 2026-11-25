import { describe, expect, it } from "vitest";

import { allWithoutCarrier } from "./shipmentDraft";

describe("allWithoutCarrier", () => {
  it("is true only when every dispatch stays inside the company", () => {
    expect(allWithoutCarrier(["INTERNAL_OUT"])).toBe(true);
    expect(allWithoutCarrier(["RW", "INTERNAL_OUT"])).toBe(true);
    expect(allWithoutCarrier(["OUT"])).toBe(false);
    expect(allWithoutCarrier(["RW", "WZ"])).toBe(false);
  });

  it("keeps the carrier when no type was found", () => {
    expect(allWithoutCarrier([])).toBe(false);
  });
});
