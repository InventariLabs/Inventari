import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";
import * as modulesCtx from "@/contexts/ModulesContext";

import {
  useReorderRules,
  useCreateReorderRule,
  useUpdateReorderRule,
  useDeleteReorderRule,
  useReplenishmentAlerts,
} from "../hooks/useReorderRules";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

beforeEach(() => {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["purchase_orders"],
    isModuleEnabled: (name: string) => name === "purchase_orders",
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
});

const mockRule = {
  id: "rule-1",
  organization_id: "org-1",
  product_template_id: "pt-1",
  product_name: "Rice 5kg",
  location_id: "loc-1",
  min_quantity: 5,
  max_quantity: 20,
  safety_stock: 2,
  preferred_partner_id: null,
  notes: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const mockAlert = {
  reorder_rule_id: "rule-1",
  product_template_id: "pt-1",
  product_name: "Rice 5kg",
  sku: "RICE-5",
  location_id: "loc-1",
  available_quantity: 3,
  min_quantity: 5,
  max_quantity: 20,
  safety_stock: 2,
  shortage: 2,
  suggested_reorder_quantity: 17,
  reserve_available_quantity: 0,
  proposed_move_quantity: 0,
  remaining_to_buy: 17,
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe("useReorderRules hooks", () => {
  it("lists rules", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/reorder-rules", () =>
        HttpResponse.json(onePage([mockRule])),
      ),
    );
    const { result } = renderHook(() => useReorderRules(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.data).toEqual([mockRule]));
  });

  it("creates a rule", async () => {
    server.use(
      http.post("/api/v1/purchase-orders/reorder-rules", () =>
        HttpResponse.json(mockRule, { status: 201 }),
      ),
    );
    const { result } = renderHook(() => useCreateReorderRule(), {
      wrapper: createWrapper(),
    });
    result.current.mutate({
      product_template_id: "pt-1",
      location_id: "loc-1",
      min_quantity: 5,
      max_quantity: 20,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("updates a rule", async () => {
    server.use(
      http.patch("/api/v1/purchase-orders/reorder-rules/rule-1", () =>
        HttpResponse.json({ ...mockRule, min_quantity: 8 }),
      ),
    );
    const { result } = renderHook(() => useUpdateReorderRule(), {
      wrapper: createWrapper(),
    });
    result.current.mutate({ id: "rule-1", data: { min_quantity: 8 } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("deletes a rule", async () => {
    server.use(
      http.delete("/api/v1/purchase-orders/reorder-rules/rule-1", () =>
        HttpResponse.json(null, { status: 204 }),
      ),
    );
    const { result } = renderHook(() => useDeleteReorderRule(), {
      wrapper: createWrapper(),
    });
    result.current.mutate("rule-1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("loads replenishment alerts with product names", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/replenishment/alerts", () =>
        HttpResponse.json(onePage([mockAlert])),
      ),
    );
    const { result } = renderHook(() => useReplenishmentAlerts(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.data).toEqual([mockAlert]));
  });
});
