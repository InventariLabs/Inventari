import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useOrganizationCurrency } from "../hooks/useOrganizationCurrency";
import { server } from "../test/mocks/server";
import { http, HttpResponse } from "msw";

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe("useOrganizationCurrency", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns currency from organization settings", async () => {
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "1", name: "Org", currency: "EUR" }),
      ),
    );

    const { result } = renderHook(() => useOrganizationCurrency(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current).toBe("EUR"));
  });

  /**
   * A guessed currency is worse than none: a Polish organization was shown
   * "$0.00" on the stats card next to "PLN 225.00" on the overview, both
   * describing the same money.
   */
  it("names no currency when the organization has not set one", async () => {
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "1", name: "Org", currency: null }),
      ),
    );

    const { result } = renderHook(() => useOrganizationCurrency(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current).toBeUndefined());
  });

  it("names no currency while the organization is still loading", async () => {
    let releaseResponse!: () => void;
    const responseReady = new Promise<void>((resolve) => {
      releaseResponse = resolve;
    });

    server.use(
      http.get("/api/v1/organizations/my", async () => {
        await responseReady;
        return HttpResponse.json({ id: "1", currency: "PLN" });
      }),
    );

    const { result, unmount } = renderHook(() => useOrganizationCurrency(), {
      wrapper: createWrapper(),
    });

    try {
      expect(result.current).toBeUndefined();
    } finally {
      releaseResponse();
      await waitFor(() => expect(result.current).toBe("PLN"));
      unmount();
    }
  });
});
