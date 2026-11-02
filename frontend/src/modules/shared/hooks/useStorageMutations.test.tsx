import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useCreateStorage,
  useUpdateStorage,
  useDeleteStorage,
  useCreateStorageHierarchy,
} from "./useStorageMutations";
import {
  useDeleteItemFromStorage,
  useConsumeItemFromStorage,
} from "@/modules/spaces/hooks/useStorageItemMutations";
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

describe("useCreateStorage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.post("/api/v1/locations", async ({ request }) => {
        const data = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            id: "new-s1",
            ...data,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
          { status: 201 },
        );
      }),
    );
  });

  it("creates a storage successfully", async () => {
    const { result } = renderHook(() => useCreateStorage(), {
      wrapper: createWrapper(),
    });

    act(() => {
      result.current.mutate({ name: "New Pantry", location_type_id: "1" });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe("new-s1");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.post("/api/v1/locations", () =>
        HttpResponse.json({ detail: "Validation error" }, { status: 422 }),
      ),
    );

    const { result } = renderHook(() => useCreateStorage(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate({ name: "" }));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useUpdateStorage", () => {
  beforeEach(() => {
    server.use(
      http.put("/api/v1/locations/:id", async ({ request, params }) => {
        const data = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          id: params.id,
          ...data,
          updated_at: new Date().toISOString(),
        });
      }),
    );
  });

  it("updates a storage successfully", async () => {
    const { result } = renderHook(() => useUpdateStorage(), {
      wrapper: createWrapper(),
    });

    act(() => {
      result.current.mutate({ id: "s1", data: { name: "Updated Pantry" } });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe("s1");
  });

  it("fails on 404", async () => {
    server.use(
      http.put("/api/v1/locations/:id", () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );

    const { result } = renderHook(() => useUpdateStorage(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate({ id: "s999", data: { name: "X" } }));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useDeleteStorage", () => {
  beforeEach(() => {
    server.use(
      http.delete(
        "/api/v1/locations/:id",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
  });

  it("deletes a storage successfully", async () => {
    const { result } = renderHook(() => useDeleteStorage(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate("s1"));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("fails on 404", async () => {
    server.use(
      http.delete("/api/v1/locations/:id", () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );

    const { result } = renderHook(() => useDeleteStorage(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate("s999"));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useCreateStorageHierarchy", () => {
  it("posts the chain to the hierarchy endpoint, so a wizard run creates every level at once", async () => {
    let body: unknown;
    server.use(
      http.post("/api/v1/locations/hierarchy", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "leaf-1", name: "Shelf" });
      }),
    );
    const { result } = renderHook(() => useCreateStorageHierarchy(), {
      wrapper: createWrapper(),
    });

    act(() => {
      result.current.mutate({
        parent_id: "root-1",
        steps: [{ name: "Pantry" }, { name: "Shelf" }],
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(body).toEqual({
      parent_id: "root-1",
      steps: [{ name: "Pantry" }, { name: "Shelf" }],
    });
    expect(result.current.data?.id).toBe("leaf-1");
  });

  it("reports a rejected chain as an error instead of a created location", async () => {
    server.use(
      http.post("/api/v1/locations/hierarchy", () =>
        HttpResponse.json({ detail: "Duplicate name" }, { status: 409 }),
      ),
    );
    const { result } = renderHook(() => useCreateStorageHierarchy(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate({ steps: [{ name: "Pantry" }] }));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useDeleteItemFromStorage", () => {
  it("deletes the product with its reason and notes, and refreshes the location's lists", async () => {
    let request: { url: string; body: unknown } | undefined;
    server.use(
      http.delete("/api/v1/items/:id", async ({ request: req }) => {
        request = { url: new URL(req.url).pathname, body: await req.json() };
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { result } = renderHook(() => useDeleteItemFromStorage("s1"), {
      wrapper: createWrapper(),
    });

    act(() => {
      result.current.mutate({
        itemId: "item-9",
        reason: "EXPIRED",
        notes: "went off",
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(request).toEqual({
      url: "/api/v1/items/item-9",
      body: { reason: "EXPIRED", notes: "went off" },
    });
  });
});

describe("useConsumeItemFromStorage", () => {
  it("consumes one unit as USED by default, so the quick Remove button needs no extra input", async () => {
    let body: unknown;
    server.use(
      http.patch("/api/v1/items/:id/consume", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "item-9", quantity: "1" });
      }),
    );
    const { result } = renderHook(() => useConsumeItemFromStorage("s1"), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate({ itemId: "item-9" }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(body).toMatchObject({ quantity: 1, reason: "USED" });
  });

  it("sends the quantity and reason it was given and surfaces a refusal as an error", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.patch("/api/v1/items/:id/consume", async ({ request }) => {
        bodies.push(await request.json());
        return bodies.length === 1
          ? HttpResponse.json({ id: "item-9", quantity: "0" })
          : HttpResponse.json({ detail: "Not enough" }, { status: 400 });
      }),
    );
    const { result } = renderHook(() => useConsumeItemFromStorage("s1"), {
      wrapper: createWrapper(),
    });

    act(() =>
      result.current.mutate({
        itemId: "item-9",
        quantity: 3,
        reason: "WASTED",
      }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(bodies[0]).toMatchObject({ quantity: 3, reason: "WASTED" });

    act(() => result.current.mutate({ itemId: "item-9", quantity: 5 }));
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
