import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useActiveShoppingList,
  useQuickAddToShoppingList,
} from "./useShoppingLists";
import { shoppingListsApi } from "@/modules/shopping_lists/api/shopping-lists";
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

  it("asks only for lists a new item can go on, never a completed one", async () => {
    let asked: URLSearchParams | undefined;
    server.use(
      http.get("/api/v1/shopping-lists", ({ request }) => {
        asked = new URL(request.url).searchParams;
        return HttpResponse.json(onePage([mockList]));
      }),
    );
    const { result } = renderHook(() => useActiveShoppingList(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(asked?.get("status")).toBe("active");
    expect(asked?.has("active_only")).toBe(false);
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

  it("picks its list among active ones, so a completed newest list is not the target", async () => {
    let asked: URLSearchParams | undefined;
    server.use(
      http.get("/api/v1/shopping-lists", ({ request }) => {
        asked = new URL(request.url).searchParams;
        return HttpResponse.json(onePage([mockList]));
      }),
    );
    const { result } = renderHook(() => useQuickAddToShoppingList(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ name: "Milk" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(asked?.get("status")).toBe("active");
    expect(asked?.has("active_only")).toBe(false);
  });
});

describe("shoppingListsApi.ensureActiveList", () => {
  it("looks for an active list, not just an unarchived one", async () => {
    let asked: URLSearchParams | undefined;
    server.use(
      http.get("/api/v1/shopping-lists", ({ request }) => {
        asked = new URL(request.url).searchParams;
        return HttpResponse.json(onePage([mockList]));
      }),
    );
    await expect(shoppingListsApi.ensureActiveList()).resolves.toMatchObject({
      id: mockList.id,
      name: mockList.name,
    });
    expect(asked?.get("status")).toBe("active");
    expect(asked?.has("active_only")).toBe(false);
  });
});
