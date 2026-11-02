import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import { useToggleRecipeFavorite } from "./useRecipes";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/**
 * The star saves, and the optimistic update knows what it is holding.
 *
 * `["recipes"]` is a prefix over two differently shaped caches: the list
 * keeps `{ items, total }`, the "what can I cook" tab keeps a plain array.
 * The updater assumed the array and called `old.map` on the object. A
 * TypeError inside `onMutate` is a failed mutation to TanStack v5, which goes
 * straight to `onError` **without calling `mutationFn`** — so the click
 * reported "could not save" and no request was ever sent.
 *
 * A test that only renders the hook cannot see this. These name the shapes.
 */
const LIST_ROWS = [
  { id: "r-1", name: "Pasta", is_favorite: false },
  { id: "r-2", name: "Soup", is_favorite: false },
];

/**
 * A client whose caches outlive the assertion.
 *
 * `src/test/mocks/reactQuery.ts` forces `gcTime: 0` on every QueryClient, so
 * a cache seeded with `setQueryData` and never observed by a component is
 * collected before the next tick — and reads back as `undefined` no matter
 * what the updater did. `setQueryDefaults` is per key and outranks the global
 * default, which is the narrowest way to keep these two caches around.
 */
function makeClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  for (const key of [["recipes"], ["recipes", "available"]]) {
    queryClient.setQueryDefaults(key, { gcTime: Infinity });
  }
  return queryClient;
}

function wrapperFor(queryClient: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

let updateCalls: string[] = [];

beforeEach(() => {
  updateCalls = [];
  server.resetHandlers();
  server.use(
    http.put("/api/v1/recipes/:id", async ({ params }) => {
      updateCalls.push(String(params.id));
      return HttpResponse.json({ id: params.id, is_favorite: true });
    }),
    http.patch("/api/v1/recipes/:id", async ({ params }) => {
      updateCalls.push(String(params.id));
      return HttpResponse.json({ id: params.id, is_favorite: true });
    }),
  );
});

describe("useToggleRecipeFavorite — the request actually leaves", () => {
  it("sends the update when the list cache is a page object", async () => {
    const queryClient = makeClient();
    queryClient.setQueryData(queryKeys.recipes.all(), {
      items: LIST_ROWS,
      total: 2,
    });

    const { result } = renderHook(() => useToggleRecipeFavorite(), {
      wrapper: wrapperFor(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync({ recipeId: "r-1", newValue: true });
    });

    await waitFor(() => expect(updateCalls).toEqual(["r-1"]));
  });

  it("marks the row inside the page without losing the page", async () => {
    const queryClient = makeClient();
    queryClient.setQueryData(queryKeys.recipes.all(), {
      items: LIST_ROWS,
      total: 2,
    });

    const { result } = renderHook(() => useToggleRecipeFavorite(), {
      wrapper: wrapperFor(queryClient),
    });

    act(() => {
      result.current.mutate({ recipeId: "r-1", newValue: true });
    });

    await waitFor(() => {
      const cached = queryClient.getQueryData(queryKeys.recipes.all()) as {
        items: { id: string; is_favorite: boolean }[];
        total: number;
      };
      expect(cached.total).toBe(2);
      expect(cached.items.find((r) => r.id === "r-1")?.is_favorite).toBe(true);
      expect(cached.items.find((r) => r.id === "r-2")?.is_favorite).toBe(false);
    });
  });

  it("still handles the plain array the available tab caches", async () => {
    // Same prefix, different shape — the reason a single assumption fails.
    const queryClient = makeClient();
    queryClient.setQueryData(queryKeys.recipes.available(), [...LIST_ROWS]);

    const { result } = renderHook(() => useToggleRecipeFavorite(), {
      wrapper: wrapperFor(queryClient),
    });

    act(() => {
      result.current.mutate({ recipeId: "r-2", newValue: true });
    });

    await waitFor(() => {
      const cached = queryClient.getQueryData(
        queryKeys.recipes.available(),
      ) as { id: string; is_favorite: boolean }[];
      expect(cached.find((r) => r.id === "r-2")?.is_favorite).toBe(true);
    });
    await waitFor(() => expect(updateCalls).toEqual(["r-2"]));
  });

  it("leaves a cache it does not recognise alone", async () => {
    // Guessing at a shape is what broke this; an unfamiliar one is not the
    // updater's business.
    const queryClient = makeClient();
    const odd = { somethingElse: 1 };
    queryClient.setQueryDefaults(["recipes", "odd-corner"], {
      gcTime: Infinity,
    });
    queryClient.setQueryData(["recipes", "odd-corner"], odd);
    queryClient.setQueryData(queryKeys.recipes.all(), {
      items: LIST_ROWS,
      total: 2,
    });

    const { result } = renderHook(() => useToggleRecipeFavorite(), {
      wrapper: wrapperFor(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync({ recipeId: "r-1", newValue: true });
    });

    expect(queryClient.getQueryData(["recipes", "odd-corner"])).toEqual(odd);
    expect(updateCalls).toEqual(["r-1"]);
  });
});
