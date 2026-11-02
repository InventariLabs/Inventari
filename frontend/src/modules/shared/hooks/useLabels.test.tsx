import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useLabels,
  useDeleteLabel,
  useBulkDeleteLabels,
  useGenerateLabels,
} from "./useLabels";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

vi.mock("../../lib/api/invalidation", () => ({
  invalidation: {
    labels: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockLabels = [
  {
    id: "1",
    short_code: "STM-0001",
    description: null,
    is_assigned: false,
    printed_at: null,
    is_item_deleted: false,
    label_type: "GENERIC",
    created_at: new Date().toISOString(),
  },
  {
    id: "2",
    short_code: "STM-0002",
    description: "Fridge label",
    is_assigned: true,
    printed_at: new Date().toISOString(),
    is_item_deleted: false,
    label_type: "GENERIC",
    created_at: new Date().toISOString(),
  },
];

const mockEnvelope = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: null,
  offset: 0,
  has_more: false,
});

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

describe("useLabels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/labels/pool", () =>
        HttpResponse.json(mockEnvelope(mockLabels)),
      ),
    );
  });

  it("returns full label pool by default", async () => {
    const { result } = renderHook(() => useLabels(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toEqual(mockLabels);
  });

  it("passes unassignedOnly=true to API", async () => {
    server.use(
      http.get("/api/v1/labels/pool", () =>
        HttpResponse.json(mockEnvelope([mockLabels[0]])),
      ),
    );

    const { result } = renderHook(() => useLabels(true), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toEqual([mockLabels[0]]);
  });

  it("passes labelType filter to API", async () => {
    server.use(
      http.get("/api/v1/labels/pool", () =>
        HttpResponse.json(mockEnvelope([])),
      ),
    );

    const { result } = renderHook(() => useLabels(false, "FOOD"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toEqual([]);
  });

  it("returns error state when API fails", async () => {
    server.use(http.get("/api/v1/labels/pool", () => HttpResponse.error()));

    const { result } = renderHook(() => useLabels(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useDeleteLabel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.delete(
        "/api/v1/labels/pool/1",
        () => new HttpResponse(null, { status: 204 }),
      ),
      http.get("/api/v1/labels/pool", () =>
        HttpResponse.json(mockEnvelope([mockLabels[1]])),
      ),
    );
  });

  it("calls delete API and invalidates labels cache", async () => {
    const { result } = renderHook(() => useDeleteLabel(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.mutate("1");
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("enters error state when delete fails", async () => {
    server.use(
      http.delete("/api/v1/labels/pool/999", () => HttpResponse.error()),
    );

    const { result } = renderHook(() => useDeleteLabel(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.mutate("999");
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useBulkDeleteLabels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.delete(
        "/api/v1/labels/pool/1",
        () => new HttpResponse(null, { status: 204 }),
      ),
      http.delete(
        "/api/v1/labels/pool/2",
        () => new HttpResponse(null, { status: 204 }),
      ),
      http.get("/api/v1/labels/pool", () =>
        HttpResponse.json(mockEnvelope([])),
      ),
    );
  });

  it("deletes each label in the array sequentially", async () => {
    const { result } = renderHook(() => useBulkDeleteLabels(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.mutate(["1", "2"]);
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useGenerateLabels", () => {
  let requestBody: { count?: number; label_type?: string } | null = null;

  beforeEach(() => {
    vi.clearAllMocks();
    requestBody = null;
    server.use(
      http.post("/api/v1/labels/pool/generate", async ({ request }) => {
        const body = (await request.json()) as {
          count?: number;
          label_type?: string;
        };
        requestBody = body;
        return HttpResponse.json(
          Array.from({ length: body.count || 1 }, (_, i) => ({
            id: `new-${i}`,
            short_code: `STM-NEW-${i}`,
            label_type: body.label_type || "GENERIC",
            is_assigned: false,
            printed_at: null,
            is_item_deleted: false,
            description: null,
            created_at: new Date().toISOString(),
          })),
          { status: 201 },
        );
      }),
      http.get("/api/v1/labels/pool", () =>
        HttpResponse.json(mockEnvelope(mockLabels)),
      ),
    );
  });

  it("sanitizes description and null-converts empty storage id", async () => {
    const { result } = renderHook(() => useGenerateLabels(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.mutate({
        count: 3,
        prefix: "STM",
        label_type: "GENERIC",
        description: "  hello  ",
        target_location_id: "",
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(requestBody).toEqual(
      expect.objectContaining({
        count: 3,
        description: "hello",
        target_location_id: null,
      }),
    );
  });

  it("invalidates labels cache after successful generation", async () => {
    const { result } = renderHook(() => useGenerateLabels(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.mutate({ count: 1, prefix: "STM", label_type: "GENERIC" });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});
