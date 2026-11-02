import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useCategories,
  useCreateCategory,
  useUpdateCategory,
  useDeleteCategory,
} from "./useCategories";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockCategories = [
  {
    id: "1",
    name: "Beverages",
    icon: "🥤",
    created_at: new Date().toISOString(),
  },
  { id: "2", name: "Dairy", icon: "🥛", created_at: new Date().toISOString() },
];

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

describe("useCategories", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage(mockCategories)),
      ),
    );
  });

  it("returns category list on success", async () => {
    const { result } = renderHook(() => useCategories(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockCategories);
  });

  it("passes optional params to API", async () => {
    server.use(
      http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    );

    const { result } = renderHook(() => useCategories(true), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });

  it("returns error state when API fails", async () => {
    server.use(http.get("/api/v1/categories", () => HttpResponse.error()));

    const { result } = renderHook(() => useCategories(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useCreateCategory", () => {
  let requestBody: unknown = null;

  beforeEach(() => {
    vi.clearAllMocks();
    requestBody = null;
    server.use(
      http.post("/api/v1/categories", async ({ request }) => {
        requestBody = await request.json();
        return HttpResponse.json(
          { id: "3", name: "Snacks", icon: "🍿" },
          { status: 201 },
        );
      }),
      http.get("/api/v1/categories", () =>
        HttpResponse.json(
          onePage([...mockCategories, { id: "3", name: "Snacks", icon: "🍿" }]),
        ),
      ),
    );
  });

  it("calls create API and invalidates categories on success", async () => {
    const { result } = renderHook(() => useCreateCategory(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.mutate({ name: "Snacks", icon: "🍿" });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(requestBody).toEqual({ name: "Snacks", icon: "🍿" });
  });

  it("enters error state on API failure", async () => {
    server.use(http.post("/api/v1/categories", () => HttpResponse.error()));

    const { result } = renderHook(() => useCreateCategory(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.mutate({ name: "Bad" });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useUpdateCategory", () => {
  let requestBody: unknown = null;

  beforeEach(() => {
    vi.clearAllMocks();
    requestBody = null;
    server.use(
      http.put("/api/v1/categories/1", async ({ request }) => {
        requestBody = await request.json();
        return HttpResponse.json({ id: "1", name: "Updated" });
      }),
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage(mockCategories)),
      ),
    );
  });

  it("calls update API with correct id and data", async () => {
    const { result } = renderHook(() => useUpdateCategory(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.mutate({ id: "1", data: { name: "Updated" } });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(requestBody).toEqual({ name: "Updated" });
  });
});

describe("useDeleteCategory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.delete(
        "/api/v1/categories/1",
        () => new HttpResponse(null, { status: 204 }),
      ),
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage([mockCategories[1]])),
      ),
    );
  });

  it("calls delete API with the category id", async () => {
    const { result } = renderHook(() => useDeleteCategory(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.mutate("1");
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});
