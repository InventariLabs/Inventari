import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useApiKeys,
  useCreateApiKey,
  useRevokeApiKey,
} from "../hooks/useApiKeys";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockApiKey = {
  id: "key1",
  name: "CI Pipeline",
  key_prefix: "inv_abc",
  is_active: true,
  last_used_at: null,
  expires_at: null,
  created_at: new Date().toISOString(),
  created_by_email: "admin@test.com",
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

describe("useApiKeys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/api-keys", () =>
        HttpResponse.json(onePage([mockApiKey])),
      ),
    );
  });

  it("returns API key list on success", async () => {
    const { result } = renderHook(() => useApiKeys(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].name).toBe("CI Pipeline");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/api-keys", () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 }),
      ),
    );
    const { result } = renderHook(() => useApiKeys(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("returns empty list when no keys exist", async () => {
    server.use(
      http.get("/api/v1/api-keys", () => HttpResponse.json(onePage([]))),
    );
    const { result } = renderHook(() => useApiKeys(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(0);
  });
});

describe("useCreateApiKey", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/api-keys", async ({ request }) => {
        const data = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            id: "key-new",
            key_prefix: "inv_xyz",
            raw_key: "inv_xyz789",
            ...data,
            created_at: new Date().toISOString(),
          },
          { status: 201 },
        );
      }),
      http.get("/api/v1/api-keys", () =>
        HttpResponse.json(onePage([mockApiKey])),
      ),
    );
  });

  it("creates an API key successfully", async () => {
    const { result } = renderHook(() => useCreateApiKey(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ name: "New Key", expires_at: null }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.raw_key).toBe("inv_xyz789");
  });

  it("fails on validation error", async () => {
    server.use(
      http.post("/api/v1/api-keys", () =>
        HttpResponse.json({ detail: "Name is required" }, { status: 422 }),
      ),
    );
    const { result } = renderHook(() => useCreateApiKey(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ name: "", expires_at: null }));
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useRevokeApiKey", () => {
  beforeEach(() => {
    server.use(
      http.delete(
        "/api/v1/api-keys/:id",
        () => new HttpResponse(null, { status: 204 }),
      ),
      http.get("/api/v1/api-keys", () =>
        HttpResponse.json(onePage([mockApiKey])),
      ),
    );
  });

  it("revokes an API key successfully", async () => {
    const { result } = renderHook(() => useRevokeApiKey(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate("key1"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("fails when key does not exist", async () => {
    server.use(
      http.delete("/api/v1/api-keys/:id", () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );
    const { result } = renderHook(() => useRevokeApiKey(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate("nonexistent"));
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
