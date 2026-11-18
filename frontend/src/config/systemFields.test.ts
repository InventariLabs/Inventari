import { describe, expect, it } from "vitest";
import { SYSTEM_FIELDS } from "./systemFields";

describe("system field presets", () => {
  it("offers short shelf lives on the expiry date, not only long ones", () => {
    // A carton of milk with five days to go is served by the short presets, not
    // the calendar: the shortcuts start at a week.
    const presets = SYSTEM_FIELDS.expiry_date.date_presets ?? [];
    expect(presets).toEqual(
      expect.arrayContaining(["plus1Week", "plus2Weeks", "plus1Month"]),
    );
    expect(presets.indexOf("plus1Week")).toBeLessThan(
      presets.indexOf("plus6Months"),
    );
  });
});
