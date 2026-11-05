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

  it("keeps the value hidden until the config has answered", async () => {
    // A profile that withholds the figure must not flash it on the first
    // paint and take it back when the answer arrives.
    let answer: (() => void) | undefined;
    server.use(
      http.get("/api/v1/stats/config", async () => {
        await new Promise<void>((resolve) => {
          answer = resolve;
        });
        return HttpResponse.json({
          enable_analytics: true,
          show_inventory_value: true,
        });
      }),
    );

    const seen: boolean[] = [];
    const { result } = renderHook(
      () => {
        const show = useShowInventoryValue();
        seen.push(show);
        return show;
      },
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(answer).toBeDefined());
    expect(result.current).toBe(false);
    answer?.();
    await waitFor(() => expect(result.current).toBe(true));
    expect(seen[0]).toBe(false);
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
