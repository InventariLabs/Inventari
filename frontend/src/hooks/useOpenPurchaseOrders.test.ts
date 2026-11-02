import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import type { components } from "@/types/api-generated";
import {
  openPurchaseOrders,
  useOpenPurchaseOrders,
  useOrderOpenReceipts,
  useOrderSupplier,
} from "./useOpenPurchaseOrders";

const modules = vi.hoisted(() => ({ enabled: true }));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    isModuleEnabled: () => modules.enabled,
    isLoading: false,
  }),
}));

type PurchaseOrder = components["schemas"]["PurchaseOrderSchema"];
type PurchaseOrderLine = components["schemas"]["PurchaseOrderLineSchema"];

function line(overrides: Partial<PurchaseOrderLine> = {}): PurchaseOrderLine {
  return {
    id: "line-1",
    purchase_order_id: "po-1",
    product_template_id: "tpl-1",
    name: "Jasmine Rice",
    quantity_ordered: "40",
    quantity_received: "0",
    unit_price: "6.20",
    uom_id: "uom-1",
    uom_symbol: "pcs",
    tax_rate: "23",
    line_number: 1,
    notes: null,
    ...overrides,
  };
}

function order(overrides: Partial<PurchaseOrder> = {}): PurchaseOrder {
  return {
    id: "po-1",
    organization_id: "org-1",
    number: "PO/2026/002",
    status: "CONFIRMED",
    partner_id: "partner-1",
    scheduled_date: null,
    notes: null,
    currency: "PLN",
    created_by: "user-1",
    confirmed_by: null,
    confirmed_at: null,
    cancelled_by: null,
    cancelled_at: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    lines: [line()],
    ...overrides,
  };
}

describe("openPurchaseOrders", () => {
  it("keeps only what the order still owes, with the count left", () => {
    const [open] = openPurchaseOrders([
      order({
        lines: [
          line({ quantity_received: "12" }),
          line({ id: "line-2", quantity_received: "40" }),
        ],
      }),
    ]);

    expect(open.lines).toHaveLength(1);
    expect(open.lines[0].outstanding).toBe("28");
    expect(open.lines[0].ordered).toBe("40");
  });

  it("leaves out an order with nothing left and puts the oldest first", () => {
    const result = openPurchaseOrders([
      order({
        id: "po-new",
        number: "PO/2026/003",
        created_at: "2026-10-05T00:00:00Z",
      }),
      order({
        id: "po-done",
        lines: [line({ quantity_received: "40" })],
      }),
      order({
        id: "po-old",
        number: "PO/2026/001",
        created_at: "2026-10-02T00:00:00Z",
      }),
    ]);

    expect(result.map((entry) => entry.number)).toEqual([
      "PO/2026/001",
      "PO/2026/003",
    ]);
  });
});

describe("useOpenPurchaseOrders", () => {
  it("asks for the supplier's confirmed orders with lines and returns what is still owed", async () => {
    modules.enabled = true;
    const seen: URLSearchParams[] = [];
    server.use(
      http.get("/api/v1/purchase-orders", ({ request }) => {
        seen.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          items: [
            order({ id: "po-a", lines: [line({ quantity_received: "15" })] }),
            order({
              id: "po-b",
              lines: [line({ quantity_received: "40" })],
            }),
          ],
          total: 2,
        });
      }),
    );

    const { result } = renderHook(() => useOpenPurchaseOrders("partner-1"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.orders).toHaveLength(1));
    expect(result.current.orders[0].lines[0].outstanding).toBe("25");
    expect(seen[0].get("partner_id")).toBe("partner-1");
    expect(seen[0].get("status")).toBe("CONFIRMED");
    expect(seen[0].get("with_lines")).toBe("true");
  });

  it("sends no request until a supplier is named", () => {
    modules.enabled = true;
    let calls = 0;
    server.use(
      http.get("/api/v1/purchase-orders", () => {
        calls += 1;
        return HttpResponse.json({ items: [], total: 0 });
      }),
    );

    const { result } = renderHook(() => useOpenPurchaseOrders(null), {
      wrapper: QueryWrapper,
    });

    expect(result.current.orders).toEqual([]);
    expect(result.current.fetchStatus).toBe("idle");
    expect(calls).toBe(0);
  });

  it("stays silent when the purchase-orders module is off", () => {
    modules.enabled = false;
    let calls = 0;
    server.use(
      http.get("/api/v1/purchase-orders", () => {
        calls += 1;
        return HttpResponse.json({ items: [], total: 0 });
      }),
    );

    const { result } = renderHook(() => useOpenPurchaseOrders("partner-1"), {
      wrapper: QueryWrapper,
    });

    expect(result.current.fetchStatus).toBe("idle");
    expect(calls).toBe(0);
    modules.enabled = true;
  });
});

describe("useOrderSupplier", () => {
  it("returns the partner of the order a link points at", async () => {
    modules.enabled = true;
    server.use(
      http.get("/api/v1/purchase-orders/po-9", () =>
        HttpResponse.json(order({ id: "po-9", partner_id: "partner-9" })),
      ),
    );

    const { result } = renderHook(() => useOrderSupplier("po-9"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.partnerId).toBe("partner-9"));
  });

  it("has no supplier and asks nothing when there is no order id", () => {
    modules.enabled = true;
    const { result } = renderHook(() => useOrderSupplier(null), {
      wrapper: QueryWrapper,
    });

    expect(result.current.partnerId).toBeNull();
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useOrderOpenReceipts", () => {
  const receipt = (id: string, status: string) => ({
    id,
    number: `REC/${id}`,
    type: "RECEIPT",
    status,
    created_at: "2026-10-02T00:00:00Z",
  });

  it("keeps the receipts that still expect goods and drops the posted ones", async () => {
    modules.enabled = true;
    server.use(
      http.get("/api/v1/purchase-orders/po-1/linked-receipts", () =>
        HttpResponse.json({
          items: [
            receipt("a", "DRAFT"),
            receipt("b", "COMPLETED"),
            receipt("c", "PENDING_APPROVAL"),
            receipt("d", "CANCELLED"),
            receipt("e", "CONFIRMED"),
          ],
          has_more: false,
        }),
      ),
    );

    const { result } = renderHook(() => useOrderOpenReceipts("po-1"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.receipts).toHaveLength(3));
    expect(result.current.receipts.map((r) => r.id)).toEqual(["a", "c", "e"]);
  });

  it("reports a failed read instead of passing it off as no open receipts", async () => {
    modules.enabled = true;
    server.use(
      http.get("/api/v1/purchase-orders/po-1/linked-receipts", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useOrderOpenReceipts("po-1"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.receipts).toEqual([]);
  });
});
