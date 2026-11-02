import { describe, expect, it } from "vitest";
import { groupLinesByUnit } from "./unitQuantities";

interface Line {
  id: string;
  unit: string | null;
}

const unitOf = (line: Line) => line.unit;

describe("groupLinesByUnit", () => {
  it("groups lines by the unit they are measured in", () => {
    const lines: Line[] = [
      { id: "a", unit: "pcs" },
      { id: "b", unit: "kg" },
      { id: "c", unit: "pcs" },
    ];

    expect(groupLinesByUnit(lines, unitOf)).toEqual([
      { unit: "pcs", lines: [lines[0], lines[2]] },
      { unit: "kg", lines: [lines[1]] },
    ]);
  });

  it("keeps a line with no unit out of every unit group", () => {
    const lines: Line[] = [
      { id: "a", unit: null },
      { id: "b", unit: "pcs" },
    ];

    expect(groupLinesByUnit(lines, unitOf)).toEqual([
      { unit: null, lines: [lines[0]] },
      { unit: "pcs", lines: [lines[1]] },
    ]);
  });

  it("treats a blank symbol as no unit", () => {
    const lines: Line[] = [{ id: "a", unit: "  " }];

    expect(groupLinesByUnit(lines, unitOf)).toEqual([
      { unit: null, lines: [lines[0]] },
    ]);
  });

  it("returns nothing for no lines", () => {
    expect(groupLinesByUnit([], unitOf)).toEqual([]);
  });
});
