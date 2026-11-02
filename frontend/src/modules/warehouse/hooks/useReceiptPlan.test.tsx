import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import type { ReceiveDraftLine } from "@/modules/warehouse/components/receive/receiveDraft";
import { useReceiptPlan } from "./useReceiptPlan";

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["warehouse"],
    isModuleEnabled: (name: string) => name === "warehouse",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

function line(over: Partial<ReceiveDraftLine>): ReceiveDraftLine {
  return {
    key: "k",
    itemId: null,
    productTemplateId: "pt-1",
    name: "Flour",
    sku: null,
    barcode: null,
    uomId: null,
    uomSymbol: null,
    ordered: null,
    quantity: "1",
    targetLocationId: null,
    batchNumber: "",
    expiryDate: "",
    unitPrice: "",
    taxRate: "",
    sourcePoLineId: null,
    chosenProductName: null,
    heldQuantity: "",
    heldCode: null,
    ...over,
  } as ReceiveDraftLine;
}

/**
 * The receive sheet's shelf preview. Asking about a row with no product or
 * no count produced a shelf for an empty line, and pairing the planner's
 * answers by position with the sheet's rows (rather than the rows actually
 * sent) put each shelf next to the wrong product once a blank row sat
 * between them.
 */
describe("useReceiptPlan — which rows are asked about and where each answer lands", () => {
  it("sends only rows with a product and a positive count, and keys each plan to its row", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post("*/warehouse/putaway/preview", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json([
          { location_id: "shelf-a" },
          { location_id: "shelf-b" },
        ]);
      }),
    );
    const lines = [
      line({ key: "a", productTemplateId: "pt-a", quantity: "2" }),
      line({ key: "blank", productTemplateId: null, itemId: null }),
      line({ key: "zero", quantity: "0" }),
      line({ key: "typing", quantity: "abc" }),
      line({
        key: "b",
        productTemplateId: null,
        itemId: "it-b",
        quantity: "5",
      }),
    ];

    const { result } = renderHook(() => useReceiptPlan(lines, "wh-1"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.plansByKey.size).toBe(2));
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({
      target_location_id: "wh-1",
      lines: [
        { product_template_id: "pt-a", quantity: "2" },
        { item_id: "it-b", quantity: "5" },
      ],
    });
    expect(result.current.plansByKey.get("a")).toEqual({
      location_id: "shelf-a",
    });
    expect(result.current.plansByKey.get("b")).toEqual({
      location_id: "shelf-b",
    });
    expect(result.current.error).toBeNull();
  });

  it("asks nothing while the receipt has no destination", async () => {
    const asked = vi.fn();
    server.use(
      http.post("*/warehouse/putaway/preview", () => {
        asked();
        return HttpResponse.json([]);
      }),
    );

    const { result } = renderHook(
      () => useReceiptPlan([line({ key: "a" })], null),
      { wrapper: QueryWrapper },
    );

    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(asked).not.toHaveBeenCalled();
    expect(result.current.plansByKey.size).toBe(0);
    expect(result.current.isFetching).toBe(false);
  });
});
