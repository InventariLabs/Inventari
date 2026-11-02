import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useActiveShoppingList,
  useQuickAddToShoppingList,
} from "./useShoppingLists";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockList = {
  id: "sl1",
  name: "Weekly Shopping",
  organization_id: "org1",
  created_by: "u1",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  items: [],
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ModulesProvider>{children}</ModulesProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

describe("useActiveShoppingList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/shopping-lists", () =>
        HttpResponse.json(onePage([mockList])),
      ),
      http.get("/api/v1/shopping-lists/:id", () => HttpResponse.json(mockList)),
    );
  });

  it("returns active shopping list when one exists", async () => {
    const { result } = renderHook(() => useActiveShoppingList(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.name).toBe("Weekly Shopping");
  });

  it("returns null when no active list", async () => {
    server.use(
      http.get("/api/v1/shopping-lists", () => HttpResponse.json(onePage([]))),
    );
    const { result } = renderHook(() => useActiveShoppingList(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeNull();
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/shopping-lists", () =>
        HttpResponse.json({ detail: "Error" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useActiveShoppingList(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useQuickAddToShoppingList", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/shopping-lists", () =>
        HttpResponse.json(onePage([mockList])),
      ),
      http.post("/api/v1/shopping-lists/:id/items", async ({ request }) => {
        const data = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "sli1", ...data }, { status: 201 });
      }),
      http.get("/api/v1/shopping-lists/:id", () =>
        HttpResponse.json({
          ...mockList,
          items: [{ id: "sli1", name: "Milk" }],
        }),
      ),
    );
  });

  it("adds item to active shopping list", async () => {
    const { result } = renderHook(() => useQuickAddToShoppingList(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate({ name: "Milk", quantity: 2, unit: "l" }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});
