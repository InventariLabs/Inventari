import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import {
  useWidgets,
  useCreateWidget,
  useUpdateWidget,
  useDeleteWidget,
} from "./useWidgets";
import type { Widget, WidgetPage } from "./types";

vi.mock("@/lib/api/client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import { api } from "@/lib/api/client";

const mockWidget: Widget = {
  id: "w-1",
  organization_id: "org-1",
  name: "Test Widget",
  color: "blue",
  quantity: 5,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function createWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
}

beforeEach(() => {
  vi.clearAllMocks();
});

function pageOf(items: Widget[]): WidgetPage {
  return {
    items,
    total: items.length,
    limit: 100,
    offset: 0,
    has_more: false,
    total_capped: false,
  };
}

describe("useWidgets", () => {
  it("fetches and returns a page of the widget list", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: pageOf([mockWidget]) });

    const { result } = renderHook(() => useWidgets(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(pageOf([mockWidget]));
    expect(api.get).toHaveBeenCalledWith("/example-widgets");
  });

  it("returns an empty page when no widgets exist", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: pageOf([]) });

    const { result } = renderHook(() => useWidgets(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toEqual([]);
    expect(result.current.data?.total).toBe(0);
  });
});

describe("useCreateWidget", () => {
  it("posts widget data and invalidates query cache", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: mockWidget });

    const { result } = renderHook(() => useCreateWidget(), {
      wrapper: createWrapper(),
    });

    result.current.mutate({ name: "Test Widget", color: "blue" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.post).toHaveBeenCalledWith("/example-widgets", {
      name: "Test Widget",
      color: "blue",
    });
  });
});

describe("useUpdateWidget", () => {
  it("patches widget data and invalidates query cache", async () => {
    vi.mocked(api.patch).mockResolvedValueOnce({ data: mockWidget });

    const { result } = renderHook(() => useUpdateWidget(), {
      wrapper: createWrapper(),
    });

    result.current.mutate({ id: "w-1", data: { quantity: 10 } });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.patch).toHaveBeenCalledWith("/example-widgets/w-1", {
      quantity: 10,
    });
  });
});

describe("useDeleteWidget", () => {
  it("deletes widget and invalidates query cache", async () => {
    vi.mocked(api.delete).mockResolvedValueOnce({} as never);

    const { result } = renderHook(() => useDeleteWidget(), {
      wrapper: createWrapper(),
    });

    result.current.mutate("w-1");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.delete).toHaveBeenCalledWith("/example-widgets/w-1");
  });
});
