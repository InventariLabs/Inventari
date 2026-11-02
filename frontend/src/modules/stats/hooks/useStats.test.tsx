import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useStatsHeadline,
  useStatsOverview,
  useStatsByStorage,
  useStatsByCategory,
  useRotationAnalysis,
  useSmartAlerts,
} from "./useStats";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockOverview = {
  total_items: 42,
  total_locations: 5,
  expiring_soon: 3,
  expired: 1,
  low_stock: 2,
};

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

describe("useStatsOverview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/stats/overview", () => HttpResponse.json(mockOverview)),
    );
  });

  it("returns overview stats on success", async () => {
    const { result } = renderHook(() => useStatsOverview(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.total_items).toBe(42);
    expect(result.current.data?.low_stock).toBe(2);
  });

  it("returns error state on API failure", async () => {
    server.use(
      http.get("/api/v1/stats/overview", () =>
        HttpResponse.json({ detail: "Error" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useStatsOverview(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useStatsHeadline", () => {
  const attentionCounts = { expired: 1, expiring_soon: 2, low_stock: 3 };

  const serveBoth = () => {
    server.use(
      http.get("/api/v1/stats/overview", () => HttpResponse.json(mockOverview)),
      http.get("/api/v1/items/attention-counts", () =>
        HttpResponse.json(attentionCounts),
      ),
    );
  };

  it("hands over the overview and the one attention count together", async () => {
    serveBoth();
    const { result } = renderHook(() => useStatsHeadline(false), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.overview.total_items).toBe(42);
    expect(result.current.data?.counts.low_stock).toBe(3);
  });

  it("reports the headline failed when either answer does", async () => {
    serveBoth();
    server.use(
      http.get("/api/v1/items/attention-counts", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useStatsHeadline(false), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  it("asks both again when the page retries", async () => {
    serveBoth();
    server.use(
      http.get("/api/v1/items/attention-counts", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useStatsHeadline(false), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    server.use(
      http.get("/api/v1/items/attention-counts", () =>
        HttpResponse.json(attentionCounts),
      ),
    );
    act(() => result.current.refetch());

    await waitFor(() => expect(result.current.data?.counts.low_stock).toBe(3));
  });
});

describe("useStatsByStorage", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/stats/by-location", () =>
        HttpResponse.json(
          onePage([
            { location_id: "s1", item_count: 10, location_name: "Pantry" },
          ]),
        ),
      ),
    );
  });

  it("returns stats by storage", async () => {
    const { result } = renderHook(() => useStatsByStorage(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });
});

describe("useStatsByCategory", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/stats/by-category", () =>
        HttpResponse.json(
          onePage([
            { category_id: "c1", item_count: 5, category_name: "Food" },
          ]),
        ),
      ),
    );
  });

  it("returns stats by category", async () => {
    const { result } = renderHook(() => useStatsByCategory(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });
});

describe("useRotationAnalysis", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/stats/rotation", () =>
        HttpResponse.json({ fast_movers: [], slow_movers: [] }),
      ),
    );
  });

  it("is disabled when enabled=false", () => {
    const { result } = renderHook(() => useRotationAnalysis(false), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches when enabled=true", async () => {
    const { result } = renderHook(() => useRotationAnalysis(true), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useSmartAlerts", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/stats/alerts", () => HttpResponse.json({ alerts: [] })),
    );
  });

  it("is disabled when enabled=false", () => {
    const { result } = renderHook(() => useSmartAlerts(false), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches alerts when enabled=true", async () => {
    const { result } = renderHook(() => useSmartAlerts(true), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});
