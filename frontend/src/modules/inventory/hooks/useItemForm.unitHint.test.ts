import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useIsFetching } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import { useItemForm } from "./useItemForm";

// react-i18next and formMemoryStore are already mocked globally in src/test/setup.ts.

// UoM ids as served by the MSW handler for /api/v1/uoms/categories:
// "1" gram (Weight), "2" kilogram (Weight), "3" piece (Count).
const GRAM = "1";
const KILOGRAM = "2";
const PIECE = "3";

vi.mock("sonner", () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

// The form reads the "Show inventory value" switch through the stats
// module's query; this file renders without that module's providers.
vi.mock("@/modules/shared/hooks/useShowInventoryValue", () => ({
  useShowInventoryValue: () => true,
}));

/** The catalogue's answer for a product the organization already keeps. */
function catalogueKnows(unitId: string, symbol: string) {
  server.use(
    http.get("/api/v1/items/product-templates/lookup", ({ request }) => {
      const url = new URL(request.url);
      return HttpResponse.json({
        product_template_id: "tpl-1",
        name: url.searchParams.get("name") ?? "Rye flour",
        brand: null,
        barcode: url.searchParams.get("barcode"),
        sku: "RYE-1",
        uom_id: unitId,
        uom_symbol: symbol,
        uom_name: symbol === "kg" ? "Kilogram" : symbol,
        image_url: null,
        description: null,
        weight_value: null,
        source: "local",
      });
    }),
  );
}

function renderItemForm(props: Parameters<typeof useItemForm>[0]) {
  return renderHook(() => useItemForm(props), { wrapper: QueryWrapper });
}

/** Types a product the catalogue knows and waits for the hint to arrive. */
async function typeMatchedProduct(
  result: { current: ReturnType<typeof useItemForm> },
  name = "Rye flour",
) {
  act(() => {
    result.current.handleInputChange("name", name);
  });
  await waitFor(() =>
    expect(result.current.templateUnit?.uomSymbol).toBe("kg"),
  );
}

describe("useItemForm — the unit the catalogue counts the product in", () => {
  beforeEach(() => {
    // MSW clears the per-test `server.use` overrides between tests; nothing
    // here restores the spies, or the `onSubmit` the assertions read would be
    // a plain function by the time they run.
  });

  it("pre-selects the template's unit and says where it comes from", async () => {
    catalogueKnows(KILOGRAM, "kg");
    const { result } = renderItemForm({ onSubmit: vi.fn() });

    await typeMatchedProduct(result);

    expect(result.current.formData.uom_id).toBe(KILOGRAM);
    expect(result.current.templateUnit).toEqual({
      productName: "Rye flour",
      uomSymbol: "kg",
      uomName: "Kilogram",
    });
  });

  it("asks the same question the save will ask, and no request leaves while it waits", async () => {
    catalogueKnows(KILOGRAM, "kg");
    const onSubmit = vi.fn();
    const { result } = renderItemForm({ onSubmit });

    await typeMatchedProduct(result);
    act(() => {
      result.current.handleInputChange("location_id", "loc-1");
    });
    // The reader picks pieces where the catalogue counts kilograms.
    act(() => {
      result.current.handleInputChange("uom_id", PIECE);
    });

    expect(result.current.pendingUnitChoice).toEqual({
      template: {
        productName: "Rye flour",
        uomSymbol: "kg",
        uomName: "Kilogram",
      },
      chosenUomId: PIECE,
      chosenSymbol: "pcs",
      chosenName: "Piece",
    });

    act(() => {
      result.current.submit();
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("sends the confirmation the server requires once the choice is confirmed", async () => {
    catalogueKnows(KILOGRAM, "kg");
    const onSubmit = vi.fn();
    const { result } = renderItemForm({ onSubmit });

    await typeMatchedProduct(result);
    act(() => {
      result.current.handleInputChange("location_id", "loc-1");
      result.current.handleInputChange("quantity", "5");
    });
    // Grams convert into kilograms, so the quantity survives the change: this
    // test is about the confirmation, not about a value the unit cannot carry.
    act(() => {
      result.current.handleInputChange("uom_id", GRAM);
    });
    act(() => {
      result.current.resolveUnitChoice(true);
    });
    // The answer landed: the form re-rendered with it, and the save that
    // follows is the one the reader pressed.
    await waitFor(() => expect(result.current.pendingUnitChoice).toBeNull());
    act(() => {
      result.current.submit();
    });

    expect(onSubmit).toHaveBeenCalledOnce();
    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.uom_id).toBe(GRAM);
    expect(payload.unit_confirmed_over_template).toBe(true);
  });

  it("puts the template's unit back when the choice is declined", async () => {
    catalogueKnows(KILOGRAM, "kg");
    const onSubmit = vi.fn();
    const { result } = renderItemForm({ onSubmit });

    await typeMatchedProduct(result);
    act(() => {
      result.current.handleInputChange("location_id", "loc-1");
      result.current.handleInputChange("quantity", "500");
    });
    act(() => {
      result.current.handleInputChange("uom_id", GRAM);
    });
    act(() => {
      result.current.resolveUnitChoice(false);
    });

    expect(result.current.pendingUnitChoice).toBeNull();
    expect(result.current.formData.uom_id).toBe(KILOGRAM);

    act(() => {
      result.current.submit();
    });
    // The template's own unit is not a choice: the form says nothing about
    // it and lets the server settle it.
    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect("uom_id" in payload).toBe(false);
    expect(payload.unit_confirmed_over_template).toBeUndefined();
  });

  it("says nothing about the unit when the catalogue does not know the product", async () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({ onSubmit });

    act(() => {
      result.current.handleInputChange("name", "Something local");
      result.current.handleInputChange("location_id", "loc-1");
    });
    await waitFor(() => expect(result.current.templateUnit).toBeNull());

    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect("uom_id" in payload).toBe(false);
    expect(payload.unit_confirmed_over_template).toBeUndefined();
  });

  it("holds the save while the catalogue cannot be asked, and saves once it answers", async () => {
    const lookups = vi.fn();
    server.use(
      http.get("/api/v1/items/product-templates/lookup", () => {
        lookups();
        return HttpResponse.json({ detail: "down" }, { status: 500 });
      }),
    );
    const onSubmit = vi.fn();
    const { result } = renderHook(
      () => ({ form: useItemForm({ onSubmit }), fetching: useIsFetching() }),
      { wrapper: QueryWrapper },
    );

    act(() => {
      result.current.form.handleInputChange("name", "Rye flour");
      result.current.form.handleInputChange("location_id", "loc-1");
    });
    // The form does not publish the failure; the read having settled is what
    // the press below depends on.
    await waitFor(() => expect(lookups).toHaveBeenCalledOnce());
    await waitFor(() => expect(result.current.fetching).toBe(0));

    catalogueKnows(KILOGRAM, "kg");
    act(() => {
      result.current.form.submit();
    });

    expect(onSubmit).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      "Could not check which unit this product is kept in. Try saving again.",
    );

    // The refused save asked again, so the second press has the answer.
    await waitFor(() =>
      expect(result.current.form.formData.uom_id).toBe(KILOGRAM),
    );
    act(() => {
      result.current.form.submit();
    });

    expect(onSubmit).toHaveBeenCalledOnce();
    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.name).toBe("Rye flour");
    // The template's own unit is the server's answer, not a choice to send.
    expect("uom_id" in payload).toBe(false);
  });

  it("confirms a unit change on an existing record without a dialog", async () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      form: "item_edit",
      initialData: {
        name: "Sugar",
        location_id: "loc-1",
        quantity: "5",
        uom_id: KILOGRAM,
      },
    });

    act(() => {
      result.current.handleInputChange("uom_id", GRAM);
    });
    act(() => {
      result.current.submit();
    });

    // Nothing to ask: moving the record onto another unit is the choice, and
    // the server gets told it was made. The dialog belongs to the case where
    // the catalogue has an answer the reader has not seen yet.
    expect(result.current.pendingUnitChoice).toBeNull();
    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.uom_id).toBe(GRAM);
    expect(payload.unit_confirmed_over_template).toBe(true);
  });
});
