import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useStockTakes,
  useStockTake,
  useCreateStockTake,
  useDeleteStockTake,
  useAddStockTakeItem,
} from "./useStockTakes";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import * as modulesCtx from "@/contexts/ModulesContext";

beforeEach(() => {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["stock_takes"],
    isModuleEnabled: (name: string) => name === "stock_takes",
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
});

const mockStockTake = {
  id: "st1",
  name: "Q1 Inventory",
  status: "IN_PROGRESS",
  location_id: "s1",
  created_at: new Date().toISOString(),
  items: [],
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

describe("useStockTakes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/stock-takes", () =>
        HttpResponse.json(onePage([mockStockTake])),
      ),
    );
  });

  it("returns stock takes list on success", async () => {
    const { result } = renderHook(() => useStockTakes(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/stock-takes", () =>
        HttpResponse.json({ detail: "Error" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useStockTakes(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useStockTake", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/stock-takes/:id", () =>
        HttpResponse.json(mockStockTake),
      ),
    );
  });

  it("fetches a single stock take", async () => {
    const { result } = renderHook(() => useStockTake("st1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe("st1");
  });

  it("is disabled when id is undefined", () => {
    const { result } = renderHook(() => useStockTake(undefined), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useCreateStockTake", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/stock-takes", async ({ request }) => {
        const data = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "st-new", ...data }, { status: 201 });
      }),
      http.get("/api/v1/stock-takes", () => HttpResponse.json(onePage([]))),
    );
  });

  it("creates a stock take", async () => {
    const { result } = renderHook(() => useCreateStockTake(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({
        name: "New Count",
        location_id: "s1",
      }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useDeleteStockTake", () => {
  beforeEach(() => {
    server.use(
      http.delete(
        "/api/v1/stock-takes/:id",
        () => new HttpResponse(null, { status: 204 }),
      ),
      http.get("/api/v1/stock-takes", () => HttpResponse.json(onePage([]))),
    );
  });

  it("deletes a stock take", async () => {
    const { result } = renderHook(() => useDeleteStockTake(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate("st1"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

// guard: server errors must reach the user — mutations carry an
// i18n errorFallback, so useAppMutation shows a toast with the server
// message (or the fallback when the server gives none).
describe("useAddStockTakeItem", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/stock-takes/:id/items", () =>
        HttpResponse.json(
          {
            detail: {
              code: "STOCK_TAKE_ITEM_ALREADY_EXISTS",
              message: "Item already exists in stock take",
            },
          },
          { status: 409 },
        ),
      ),
    );
  });

  it("shows an error toast with the server message on 409", async () => {
    const { result } = renderHook(() => useAddStockTakeItem("st-1"), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ itemId: "1", quantity: 3 }));
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).toHaveBeenCalledWith(
      "Item already exists in stock take",
    );
  });
});
