import { renderHook } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { useUomPrecision } from "./useUomPrecision";

const { mockUseFlatUoms } = vi.hoisted(() => ({
  mockUseFlatUoms: { useFlatUoms: vi.fn() },
}));

vi.mock("@/modules/shared/hooks/useUoms", () => mockUseFlatUoms);

function uomsWith(rounding: unknown) {
  return [{ id: "uom-cm", symbol: "cm", name: "centimetre", rounding }];
}

beforeEach(() => {
  mockUseFlatUoms.useFlatUoms.mockReset();
});

describe("useUomPrecision", () => {
  it("counts the places the step keeps, not the wire text's scale", () => {
    // The API serializes rounding as the column's text ('0.010000',
    // numeric(12,6)): its string scale is 6, the step the unit keeps is 2 —
    // the count the server's refusal names.
    mockUseFlatUoms.useFlatUoms.mockReturnValue({
      data: uomsWith("0.010000"),
    });

    const { result } = renderHook(() => useUomPrecision("uom-cm"));

    expect(result.current.decimalPlaces).toBe(2);
    expect(result.current.stepString).toBe("0.01");
    expect(result.current.step).toBe(0.01);
    expect(result.current.min).toBe(0.01);
    expect(result.current.isInteger).toBe(false);
  });

  it("keeps three places for a milli-step", () => {
    mockUseFlatUoms.useFlatUoms.mockReturnValue({
      data: uomsWith("0.001000"),
    });

    const { result } = renderHook(() => useUomPrecision("uom-cm"));

    expect(result.current.decimalPlaces).toBe(3);
    expect(result.current.stepString).toBe("0.001");
  });

  it("reads whole-number units off either spelling of one", () => {
    mockUseFlatUoms.useFlatUoms.mockReturnValue({
      data: uomsWith("1.000000"),
    });

    const { result } = renderHook(() => useUomPrecision("uom-cm"));

    expect(result.current.isInteger).toBe(true);
    expect(result.current.decimalPlaces).toBe(0);
    expect(result.current.stepString).toBe("1");
  });

  it("floors a step finer than the quantity columns' scale, like the server", () => {
    // The server floors the unit's step at the quantity columns' scale
    // (0.001) before it counts places; a unit seeded finer would otherwise
    // have the hint promise places the database rounds away.
    mockUseFlatUoms.useFlatUoms.mockReturnValue({
      data: uomsWith("0.000100"),
    });

    const { result } = renderHook(() => useUomPrecision("uom-cm"));

    expect(result.current.decimalPlaces).toBe(3);
    expect(result.current.step).toBe(0.001);
    expect(result.current.min).toBe(0.001);
  });

  it("answers the same when a numeric rounding arrives instead of text", () => {
    // Hand-written types disagree about rounding's type (number vs string);
    // the count may not depend on which one is right.
    mockUseFlatUoms.useFlatUoms.mockReturnValue({ data: uomsWith(0.01) });

    const { result } = renderHook(() => useUomPrecision("uom-cm"));

    expect(result.current.decimalPlaces).toBe(2);
  });

  it("falls back permissively without a uom id", () => {
    mockUseFlatUoms.useFlatUoms.mockReturnValue({ data: uomsWith("0.01") });

    const { result } = renderHook(() => useUomPrecision(null));

    expect(result.current.stepString).toBe("any");
    expect(result.current.decimalPlaces).toBe(3);
  });
});
