import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useItems, useItem, useItemSearch } from "./useItems";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

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

describe("useItems", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns items list on success", async () => {
    const { result } = renderHook(() => useItems(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.items[0].name).toBe("Test Item");
  });

  it("returns error state on API failure", async () => {
    server.use(
      http.get("/api/v1/items", () =>
        HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useItems(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("includes params in query key when provided", async () => {
    const { result } = renderHook(
      () => useItems({ search: "milk", category_id: "cat-1" }),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useItem", () => {
  it("fetches single item by id", async () => {
    const { result } = renderHook(() => useItem("1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe("1");
  });

  it("is disabled when itemId is empty", () => {
    const { result } = renderHook(() => useItem(""), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("returns error state on API failure", async () => {
    server.use(
      http.get("/api/v1/items/:id", () =>
        HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
      ),
    );
    const { result } = renderHook(() => useItem("999"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useItemSearch", () => {
  it("is disabled when query is empty", () => {
    const { result } = renderHook(() => useItemSearch(""), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches when query is non-empty", async () => {
    const { result } = renderHook(() => useItemSearch("milk"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});
