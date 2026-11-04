import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  usePurchaseOrders,
  usePurchaseOrder,
  useCreatePurchaseOrder,
  useConfirmPurchaseOrder,
  useCancelPurchaseOrder,
  usePOSettings,
  useUpdatePOSettings,
  useRequestPOApproval,
  useApprovePO,
  useRejectPO,
  usePOApprovalRequirement,
} from "./usePurchaseOrders";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { queryKeys } from "@/hooks/queries/keys";
import type { PurchaseOrder } from "../types/purchase-orders";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const modules = vi.hoisted(() => ({
  enabled: ["purchase_orders"] as string[],
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useEnabledModulesOptional: () => modules.enabled,
  useModules: () => ({
    enabledModules: modules.enabled,
    isModuleEnabled: (name: string) => modules.enabled.includes(name),
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

const mockPO = {
  id: "po-1",
  organization_id: "org-1",
  number: "PO/2026/001",
  status: "DRAFT",
  partner_id: "partner-1",
  scheduled_date: "2026-05-01",
  notes: null,
  created_by: "user-1",
  confirmed_by: null,
  confirmed_at: null,
  cancelled_by: null,
  cancelled_at: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  lines: [
    {
      id: "line-1",
      purchase_order_id: "po-1",
      product_template_id: "pt-1",
      name: "Piwo Tyskie",
      quantity_ordered: 24,
      quantity_received: 0,
      unit_price: "18.50",
      line_number: 1,
      notes: null,
    },
  ],
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe("usePurchaseOrders", () => {
  let requestedUrl = "";

  beforeEach(() => {
    requestedUrl = "";
    server.use(
      http.get("/api/v1/purchase-orders", ({ request }) => {
        requestedUrl = request.url;
        return HttpResponse.json({
          items: [mockPO],
          total: 1,
          limit: 20,
          offset: 20,
          has_more: false,
        });
      }),
    );
  });

  it("returns paginated purchase orders and sends list filters", async () => {
    const { result } = renderHook(
      () =>
        usePurchaseOrders({
          search: "priority",
          status: "CONFIRMED",
          limit: 20,
          offset: 20,
        }),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.items[0].number).toBe("PO/2026/001");
    expect(result.current.data?.total).toBe(1);
    expect(requestedUrl).toContain("search=priority");
    expect(requestedUrl).toContain("status=CONFIRMED");
    expect(requestedUrl).toContain("limit=20");
    expect(requestedUrl).toContain("offset=20");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 }),
      ),
    );
    const { result } = renderHook(() => usePurchaseOrders(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("usePurchaseOrder", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/purchase-orders/po-1", () => HttpResponse.json(mockPO)),
    );
  });

  it("returns single purchase order", async () => {
    const { result } = renderHook(() => usePurchaseOrder("po-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.number).toBe("PO/2026/001");
    expect(result.current.data?.lines).toHaveLength(1);
  });

  it("does not fetch when id is empty", async () => {
    const { result } = renderHook(() => usePurchaseOrder(""), {
      wrapper: createWrapper(),
    });
    expect(result.current.isFetching).toBe(false);
  });
});

describe("useCreatePurchaseOrder", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/purchase-orders", async ({ request }) => {
        const data = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { ...mockPO, ...data, id: "po-new" },
          { status: 201 },
        );
      }),
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ items: [mockPO], total: 1 }),
      ),
    );
  });

  it("creates purchase order successfully", async () => {
    const { result } = renderHook(() => useCreatePurchaseOrder(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({
        partner_id: "partner-1",
        lines: [{ name: "Test", quantity_ordered: 10, unit_price: "5.00" }],
      }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("fails on validation error", async () => {
    server.use(
      http.post("/api/v1/purchase-orders", () =>
        HttpResponse.json({ detail: "Validation error" }, { status: 422 }),
      ),
    );
    const { result } = renderHook(() => useCreatePurchaseOrder(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({
        lines: [],
      }),
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useConfirmPurchaseOrder", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/purchase-orders/po-1/confirm", () =>
        HttpResponse.json({ ...mockPO, status: "CONFIRMED" }),
      ),
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ items: [mockPO], total: 1 }),
      ),
    );
  });

  it("confirms purchase order successfully", async () => {
    const { result } = renderHook(() => useConfirmPurchaseOrder(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate("po-1"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("refreshes the approvals, the confirmation may have raised a request", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useConfirmPurchaseOrder(), {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>{children}</BrowserRouter>
        </QueryClientProvider>
      ),
    });
    act(() => result.current.mutate("po-1"));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        queryKey: queryKeys.approvals.all,
      }),
    );
  });
});

describe("useCancelPurchaseOrder", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/purchase-orders/po-1/cancel", () =>
        HttpResponse.json({ ...mockPO, status: "CANCELLED" }),
      ),
      http.get("/api/v1/purchase-orders", () =>
        HttpResponse.json({ items: [mockPO], total: 1 }),
      ),
    );
  });

  it("cancels purchase order successfully", async () => {
    const { result } = renderHook(() => useCancelPurchaseOrder(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate("po-1"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("refreshes the notification bell, the order's approval request is withdrawn with it", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useCancelPurchaseOrder(), {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>{children}</BrowserRouter>
        </QueryClientProvider>
      ),
    });
    act(() => result.current.mutate("po-1"));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        queryKey: queryKeys.notifications.all,
      }),
    );
  });
});

const mockSettings = {
  id: "settings-1",
  organization_id: "org-1",
  approval_threshold: 100,
  approval_required: false,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const mockApprovalRequest = {
  id: "req-1",
  organization_id: "org-1",
  workflow_id: "wf-1",
  target_type: "purchase_order",
  target_id: "po-1",
  status: "PENDING",
  current_stage: 1,
  total_stages: 1,
  created_by: "user-1",
  cancelled_by: null,
  cancelled_at: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  decisions: [],
};

describe("usePOSettings", () => {
  it("returns PO approval settings", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/settings", () =>
        HttpResponse.json(mockSettings),
      ),
    );
    const { result } = renderHook(() => usePOSettings(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.approval_threshold).toBe(100);
    expect(result.current.data?.approval_required).toBe(false);
  });
});

describe("useUpdatePOSettings", () => {
  it("updates settings and returns the persisted values", async () => {
    let receivedBody: unknown = null;
    server.use(
      http.put("/api/v1/purchase-orders/settings", async ({ request }) => {
        receivedBody = await request.json();
        return HttpResponse.json({
          ...mockSettings,
          approval_threshold: 250,
        });
      }),
    );
    const { result } = renderHook(() => useUpdatePOSettings(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ approval_threshold: 250 }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(receivedBody).toEqual({ approval_threshold: 250 });
    expect(result.current.data?.approval_threshold).toBe(250);
  });
});

describe("useRequestPOApproval", () => {
  it("requests approval for a PO", async () => {
    server.use(
      http.post("/api/v1/purchase-orders/po-1/request-approval", () =>
        HttpResponse.json(mockApprovalRequest, { status: 201 }),
      ),
    );
    const { result } = renderHook(() => useRequestPOApproval(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate("po-1"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe("req-1");
  });
});

describe("useApprovePO", () => {
  it("approves a PO with optional notes", async () => {
    let receivedBody: unknown = null;
    server.use(
      http.post("/api/v1/purchase-orders/po-1/approve", async ({ request }) => {
        receivedBody = await request.json();
        return HttpResponse.json({
          ...mockApprovalRequest,
          status: "APPROVED",
        });
      }),
    );
    const { result } = renderHook(() => useApprovePO(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ poId: "po-1", notes: "LGTM" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(receivedBody).toEqual({ notes: "LGTM" });
    expect(result.current.data?.status).toBe("APPROVED");
  });
});

describe("useRejectPO", () => {
  it("rejects a PO and returns the updated request", async () => {
    server.use(
      http.post("/api/v1/purchase-orders/po-1/reject", () =>
        HttpResponse.json({ ...mockApprovalRequest, status: "REJECTED" }),
      ),
    );
    const { result } = renderHook(() => useRejectPO(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ poId: "po-1", notes: "too expensive" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.status).toBe("REJECTED");
  });

  it("surfaces API errors", async () => {
    server.use(
      http.post("/api/v1/purchase-orders/po-1/reject", () =>
        HttpResponse.json(
          {
            detail: {
              code: "APPROVAL_ERROR",
              message: "No active approval request",
              lang: "en",
            },
          },
          { status: 409 },
        ),
      ),
    );
    const { result } = renderHook(() => useRejectPO(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ poId: "po-1" }));
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

type POStatus = PurchaseOrder["status"];

describe("usePOApprovalRequirement", () => {
  beforeEach(() => {
    modules.enabled = ["purchase_orders", "approvals"];
  });

  const asked = (status: POStatus) => {
    const calls: string[] = [];
    server.use(
      http.get("/api/v1/purchase-orders/:po_id/approval-requirement", () => {
        calls.push(status);
        return HttpResponse.json({
          approval_required: false,
          approval_solvable: false,
          undecidable_reason: "named_approvers_cannot_decide",
          undecidable_stage: "Director",
        });
      }),
    );
    return calls;
  };

  it.each<POStatus>(["DRAFT", "PENDING_APPROVAL"])(
    "asks the server about an order that is %s",
    async (status) => {
      const calls = asked(status);
      const { result } = renderHook(
        () => usePOApprovalRequirement({ id: "po-1", status }),
        { wrapper: createWrapper() },
      );
      await waitFor(() =>
        expect(result.current?.undecidable_stage).toBe("Director"),
      );
      expect(calls).toHaveLength(1);
    },
  );

  it("does not ask about an order past approval", async () => {
    const calls = asked("CONFIRMED");
    const { result } = renderHook(
      () => usePOApprovalRequirement({ id: "po-1", status: "CONFIRMED" }),
      { wrapper: createWrapper() },
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(result.current).toBeUndefined();
    expect(calls).toHaveLength(0);
  });
});
