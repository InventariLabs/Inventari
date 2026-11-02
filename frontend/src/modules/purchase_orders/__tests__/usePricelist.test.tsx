import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import * as modulesCtx from "@/contexts/ModulesContext";

import {
  usePricelistForPartner,
  usePricelistForTemplate,
  useBestPriceForTemplate,
  useCreatePricelist,
  useUpdatePricelist,
  useDeletePricelist,
} from "../hooks/usePricelist";
import { onePage } from "@/test/mocks/page";

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

const mockEntry = {
  id: "pl-1",
  organization_id: "org-1",
  partner_id: "partner-1",
  product_template_id: "pt-1",
  unit_price: 12.5,
  currency: "USD",
  uom_id: null,
  min_quantity: null,
  valid_from: "2026-01-01",
  valid_to: null,
  notes: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe("usePricelist hooks", () => {
  it("lists prices for a partner", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/pricelist/by-partner/partner-1", () =>
        HttpResponse.json(onePage([mockEntry])),
      ),
    );
    const { result } = renderHook(() => usePricelistForPartner("partner-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.data).toEqual([mockEntry]));
  });

  it("lists offers for a template (comparison)", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/pricelist/by-template/pt-1", () =>
        HttpResponse.json(onePage([mockEntry])),
      ),
    );
    const { result } = renderHook(() => usePricelistForTemplate("pt-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.data).toEqual([mockEntry]));
  });

  it("returns the best price for a template", async () => {
    server.use(
      http.get("/api/v1/purchase-orders/pricelist/best-for-template/pt-1", () =>
        HttpResponse.json(mockEntry),
      ),
    );
    const { result } = renderHook(() => useBestPriceForTemplate("pt-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.data).toEqual(mockEntry));
  });

  it("creates a price entry", async () => {
    server.use(
      http.post("/api/v1/purchase-orders/pricelist", () =>
        HttpResponse.json(mockEntry, { status: 201 }),
      ),
    );
    const { result } = renderHook(() => useCreatePricelist(), {
      wrapper: createWrapper(),
    });
    result.current.mutate({
      partner_id: "partner-1",
      product_template_id: "pt-1",
      unit_price: 12.5,
      valid_from: "2026-01-01",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("updates a price entry", async () => {
    server.use(
      http.patch("/api/v1/purchase-orders/pricelist/pl-1", () =>
        HttpResponse.json({ ...mockEntry, unit_price: 10 }),
      ),
    );
    const { result } = renderHook(() => useUpdatePricelist(), {
      wrapper: createWrapper(),
    });
    result.current.mutate({ id: "pl-1", data: { unit_price: 10 } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("deletes a price entry", async () => {
    server.use(
      http.delete("/api/v1/purchase-orders/pricelist/pl-1", () =>
        HttpResponse.json(null, { status: 204 }),
      ),
    );
    const { result } = renderHook(() => useDeletePricelist(), {
      wrapper: createWrapper(),
    });
    result.current.mutate("pl-1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});
