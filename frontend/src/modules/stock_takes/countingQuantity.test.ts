import { describe, it, expect } from "vitest";
import {
  countedAmount,
  decimalsAllowedBy,
  fitsUnitStep,
} from "./countingQuantity";

describe("countedAmount", () => {
  it("reads a decimal the way it was typed", () => {
    expect(countedAmount("2.1")).toBe(2.1);
  });

  it("accepts the comma a European keyboard puts there", () => {
    expect(countedAmount("2,1")).toBe(2.1);
  });

  it("reads a number still being typed as the part already there", () => {
    // "2." is one keystroke inside "2.1"; answering null here would blank the
    // box under the typist's finger.
    expect(countedAmount("2.")).toBe(2);
  });

  it("calls an empty box nothing rather than zero", () => {
    expect(countedAmount("")).toBeNull();
    expect(countedAmount("   ")).toBeNull();
    expect(countedAmount(undefined)).toBeNull();
  });

  it("refuses text that is not a count", () => {
    expect(countedAmount("abc")).toBeNull();
    expect(countedAmount("-1")).toBeNull();
    expect(countedAmount("1e3")).toBeNull();
  });
});

describe("fitsUnitStep", () => {
  it("lets a kilogram be stated in thousandths", () => {
    expect(fitsUnitStep(2.1, "0.001000")).toBe(true);
    expect(fitsUnitStep(2.103, "0.001000")).toBe(true);
  });

  it("refuses more decimals than the unit's step", () => {
    expect(fitsUnitStep(2.1234, "0.001000")).toBe(false);
  });

  it("refuses a fraction of something counted in pieces", () => {
    expect(fitsUnitStep(3.5, "1.000000")).toBe(false);
    expect(fitsUnitStep(3, "1.000000")).toBe(true);
  });

  it("asks nothing of a row that carries no unit", () => {
    expect(fitsUnitStep(3.5, null)).toBe(true);
    expect(fitsUnitStep(3.5, undefined)).toBe(true);
  });
});

describe("decimalsAllowedBy", () => {
  it("counts the places the step leaves, not the zeros the column carries", () => {
    // numeric(12,6) serializes 0.001 as "0.001000"; the message must say
    // three places, which is what the unit actually allows.
    expect(decimalsAllowedBy("0.001000")).toBe(3);
    expect(decimalsAllowedBy("0.01")).toBe(2);
    expect(decimalsAllowedBy("1.000000")).toBe(0);
  });
});
