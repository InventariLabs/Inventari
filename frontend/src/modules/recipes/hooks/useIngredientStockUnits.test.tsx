import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryWrapper } from "@/test/queryWrapper";
import { useIngredientStockUnits } from "./useIngredientStockUnits";
import { productTemplatesApi } from "@/lib/api/productTemplates";

vi.mock("@/lib/api/productTemplates", () => ({
  productTemplatesApi: { get: vi.fn() },
}));

describe("useIngredientStockUnits", () => {
  it("maps each linked template to its stock unit", async () => {
    vi.mocked(productTemplatesApi.get).mockResolvedValue({
      uom_id: "u-kg",
      weight_value: null,
      weight_uom_id: null,
      volume_value: null,
      volume_uom_id: null,
    } as never);

    const { result } = renderHook(() => useIngredientStockUnits(["tpl-1"]), {
      wrapper: QueryWrapper,
    });

    await waitFor(() =>
      expect(result.current.stockUnits).toEqual({
        "tpl-1": { uomId: "u-kg", measureUomIds: [] },
      }),
    );
    expect(result.current.isError).toBe(false);
  });

  it("carries the units of the weight and volume the card states per piece", async () => {
    vi.mocked(productTemplatesApi.get).mockResolvedValue({
      uom_id: "u-pack",
      weight_value: 1,
      weight_uom_id: "u-kg",
      volume_value: null,
      volume_uom_id: "u-l",
    } as never);

    const { result } = renderHook(() => useIngredientStockUnits(["tpl-1"]), {
      wrapper: QueryWrapper,
    });

    // The volume unit is on the card but has no value: it is not a measure.
    await waitFor(() =>
      expect(result.current.stockUnits).toEqual({
        "tpl-1": { uomId: "u-pack", measureUomIds: ["u-kg"] },
      }),
    );
  });

  it("reports a failed read instead of an empty map that reads as 'nothing to restrict'", async () => {
    vi.mocked(productTemplatesApi.get).mockRejectedValue(new Error("down"));

    const { result } = renderHook(() => useIngredientStockUnits(["tpl-1"]), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.stockUnits).toEqual({});
  });
});
