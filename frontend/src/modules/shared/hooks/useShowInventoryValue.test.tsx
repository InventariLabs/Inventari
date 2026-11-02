import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { useShowInventoryValue } from "./useShowInventoryValue";
import { useStatsConfig } from "@/modules/stats/hooks/useStats";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <BrowserRouter>{children}</BrowserRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

/**
 * The one decision the surfaces outside the stats module read — the
 * products list's footer, the record's overview, the valuation section
 * and the stock-as-of report.
 */
describe("useShowInventoryValue", () => {
  it("reads the setting off the module config", async () => {
    server.use(
      http.get("/api/v1/stats/config", () =>
        HttpResponse.json({
          enable_analytics: true,
          show_inventory_value: false,
        }),
      ),
    );

    const { result } = renderHook(() => useShowInventoryValue(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current).toBe(false));
  });

  it("fails open while the config cannot be read", async () => {
    server.use(
      http.get("/api/v1/stats/config", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const { result } = renderHook(
      () => ({ config: useStatsConfig(), show: useShowInventoryValue() }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.config.isError).toBe(true));
    expect(result.current.show).toBe(true);
  });
});
