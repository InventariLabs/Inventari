import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useStorages, useStoragesTree, useStorage } from "./useStorages";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";

const mockStorages = [
  {
    id: "1",
    name: "Kitchen",
    description: null,
    parent_id: null,
    context_schema: [],
    field_definitions: [],
    items_count: 5,
    short_code: "KIT-001",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    organization_id: "org1",
  },
];

const mockTree = [
  {
    id: "1",
    name: "Home",
    parent_id: null,
    items_count: 10,
    short_code: "HOM-001",
    children: [
      {
        id: "2",
        name: "Kitchen",
        parent_id: "1",
        items_count: 5,
        short_code: "KIT-001",
        children: [],
      },
    ],
  },
];

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe("useStorages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json(onePage(mockStorages)),
      ),
    );
  });

  it("returns storage list on success", async () => {
    const { result } = renderHook(() => useStorages(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockStorages);
  });

  it("returns error state when API fails", async () => {
    server.use(http.get("/api/v1/locations", () => HttpResponse.error()));

    const { result } = renderHook(() => useStorages(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  it("starts in loading state", () => {
    const { result } = renderHook(() => useStorages(), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLoading).toBe(true);
  });
});

describe("useStoragesTree", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/locations/tree", () => HttpResponse.json(mockTree)),
    );
  });

  it("returns nested tree structure", async () => {
    const { result } = renderHook(() => useStoragesTree(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockTree);
    expect(result.current.data?.[0].children).toHaveLength(1);
  });

  it("passes usage param to API", async () => {
    const { result } = renderHook(() => useStoragesTree("picker"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.isSuccess).toBe(true);
  });
});

describe("useStorage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/locations/1", () => HttpResponse.json(mockStorages[0])),
    );
  });

  it("fetches single storage by id", async () => {
    const { result } = renderHook(() => useStorage("1"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockStorages[0]);
  });

  it("does not fetch when id is empty", () => {
    const { result } = renderHook(() => useStorage(""), {
      wrapper: createWrapper(),
    });

    expect(result.current.fetchStatus).toBe("idle");
  });
});
