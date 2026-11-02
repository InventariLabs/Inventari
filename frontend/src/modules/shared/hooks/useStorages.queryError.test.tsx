import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { useAuthStore } from "@/store/authStore";
import { useStorageTypesTrackExpiry } from "./useStorages";

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <ModulesProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
}

const fail = (path: string) =>
  http.get(path, () => HttpResponse.json({ detail: "boom" }, { status: 500 }));

beforeEach(() => {
  useAuthStore.setState({ isAuthenticated: true, isLoading: false });
  server.resetHandlers();
});

const type = (id: string, behavior_mode: string) => ({
  id,
  name: id,
  type_code: id.toUpperCase(),
  behavior_mode,
  is_system: false,
});

const serveTypes = (rows: ReturnType<typeof type>[]) =>
  http.get("/api/v1/location-types", () => HttpResponse.json(onePage(rows)));

describe("useStorageTypesTrackExpiry", () => {
  it("asks for the total of the locations of the expiry kinds, never for the tree", async () => {
    const seen: URLSearchParams[] = [];
    const treeReads: string[] = [];
    server.use(
      serveTypes([
        type("fridge", "EXPIRY"),
        type("freezer", "FREEZING"),
        type("shelf", "STOCK"),
      ]),
      http.get("/api/v1/locations/tree", ({ request }) => {
        treeReads.push(request.url);
        return HttpResponse.json([]);
      }),
      http.get("/api/v1/locations", ({ request }) => {
        seen.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          items: [],
          total: 3,
          limit: 1,
          offset: 0,
          has_more: true,
        });
      }),
    );
    const { result } = renderHook(() => useStorageTypesTrackExpiry(), {
      wrapper,
    });

    await waitFor(() => expect(result.current).toBe(true));
    expect(seen).toHaveLength(1);
    expect(seen[0].getAll("type_ids").sort()).toEqual(["freezer", "fridge"]);
    expect(seen[0].get("limit")).toBe("1");
    expect(treeReads).toEqual([]);
  });

  it("is false without asking when no kind of place watches expiry", async () => {
    const asked = vi.fn();
    server.use(
      serveTypes([type("shelf", "STOCK")]),
      http.get("/api/v1/locations", () => {
        asked();
        return HttpResponse.json(onePage([]));
      }),
    );
    const { result } = renderHook(() => useStorageTypesTrackExpiry(), {
      wrapper,
    });

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(result.current).toBe(false);
    expect(asked).not.toHaveBeenCalled();
  });

  it("is false when no location is of an expiry kind", async () => {
    server.use(
      serveTypes([type("fridge", "EXPIRY")]),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );
    const { result } = renderHook(() => useStorageTypesTrackExpiry(), {
      wrapper,
    });

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(result.current).toBe(false);
  });

  it("keeps the expiry views when the kinds did not arrive", async () => {
    server.use(fail("/api/v1/location-types"));
    const { result } = renderHook(() => useStorageTypesTrackExpiry(), {
      wrapper,
    });

    await waitFor(() => expect(result.current).toBe(true));
  });

  it("keeps the expiry views when the locations did not arrive", async () => {
    server.use(
      serveTypes([type("fridge", "EXPIRY")]),
      fail("/api/v1/locations"),
    );
    const { result } = renderHook(() => useStorageTypesTrackExpiry(), {
      wrapper,
    });

    await waitFor(() => expect(result.current).toBe(true));
  });
});
