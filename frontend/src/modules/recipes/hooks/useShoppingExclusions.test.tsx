import React from "react";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useCreateShoppingExclusion,
  useDeleteShoppingExclusion,
} from "./useMealPlans";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/**
 * The "Add missing" door reads `excluded` off the recipe availability. An
 * exclusion changed on the very screen — the home toggle on a row — left
 * that cache untouched, so the button stayed live over a click that added
 * zero lines (or stayed dead after the exclusion was lifted) until a manual
 * refresh. These pin that the mutations mark the availability stale.
 */
const AVAILABILITY_KEY = queryKeys.recipes.availability("r1", 4);
const RECIPE_DETAIL_KEY = queryKeys.recipes.detail("r1");
const AVAILABLE_TAB_KEY = queryKeys.recipes.available();

function makeClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  for (const key of [AVAILABILITY_KEY, RECIPE_DETAIL_KEY, AVAILABLE_TAB_KEY]) {
    queryClient.setQueryDefaults(key, { gcTime: Infinity });
  }
  queryClient.setQueryData(AVAILABILITY_KEY, { ingredients: [] });
  queryClient.setQueryData(RECIPE_DETAIL_KEY, { id: "r1" });
  queryClient.setQueryData(AVAILABLE_TAB_KEY, []);
  return queryClient;
}

function wrapperFor(queryClient: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.post("/api/v1/recipes/meal-plans/exclusions", () =>
      HttpResponse.json({
        id: "e1",
        name: "Fresh Basil",
        name_normalized: "fresh basil",
        template_id: null,
        created_at: "2026-10-04T12:00:00Z",
      }),
    ),
    http.delete(
      "/api/v1/recipes/meal-plans/exclusions/:id",
      () => new HttpResponse(null, { status: 204 }),
    ),
  );
});

describe("shopping exclusion mutations invalidate the availability door", () => {
  it("marks recipe availability stale after adding an exclusion", async () => {
    const queryClient = makeClient();
    const { result } = renderHook(() => useCreateShoppingExclusion(), {
      wrapper: wrapperFor(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync({ name: "Fresh Basil" });
    });

    expect(queryClient.getQueryState(AVAILABILITY_KEY)?.isInvalidated).toBe(
      true,
    );
  });

  it("marks recipe availability stale after removing an exclusion", async () => {
    const queryClient = makeClient();
    const { result } = renderHook(() => useDeleteShoppingExclusion(), {
      wrapper: wrapperFor(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync("e1");
    });

    expect(queryClient.getQueryState(AVAILABILITY_KEY)?.isInvalidated).toBe(
      true,
    );
  });

  it("leaves caches that do not answer the shopping question alone", async () => {
    const queryClient = makeClient();
    const { result } = renderHook(() => useCreateShoppingExclusion(), {
      wrapper: wrapperFor(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync({ name: "Fresh Basil" });
    });

    expect(queryClient.getQueryState(RECIPE_DETAIL_KEY)?.isInvalidated).toBe(
      false,
    );
    expect(queryClient.getQueryState(AVAILABLE_TAB_KEY)?.isInvalidated).toBe(
      false,
    );
  });
});
