import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useCreateMakerRecipe,
  useMakerSettings,
  useMakerRecipe,
  useMakerRecipeCatalog,
} from "./useRecipes";

/**
 * The rest of the maker suite mocks this whole module
 * (`vi.mock("@/modules/maker/hooks/useRecipes")`), so its 50 green tests say
 * nothing about the hooks themselves. These exercise the real ones against
 * MSW and record the path each one actually asked for: a hook pointed at
 * the wrong endpoint stays green when a neighbouring handler answers it.
 */

const enabledModules = vi.hoisted(() => ({ current: ["maker"] }));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: enabledModules.current,
    isLoading: false,
    isModuleEnabled: (name: string) =>
      enabledModules.current.includes(name) || name === "core",
    refreshModules: vi.fn(),
  }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { Wrapper, queryClient };
}

beforeEach(() => {
  enabledModules.current = ["maker"];
});

describe("maker recipe hooks — endpoints", () => {
  it("useMakerRecipeCatalog calls GET /maker/recipes, not a neighbouring route", async () => {
    const seen: string[] = [];
    server.use(
      http.get("*/maker/recipes", ({ request }) => {
        seen.push(new URL(request.url).pathname);
        return HttpResponse.json({
          items: [],
          total: 0,
          limit: 50,
          offset: 0,
          has_more: false,
        });
      }),
    );

    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useMakerRecipeCatalog(), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seen).toEqual(["/api/v1/maker/recipes"]);
  });

  it("useMakerSettings calls GET /maker/settings", async () => {
    const seen: string[] = [];
    server.use(
      http.get("*/maker/settings", ({ request }) => {
        seen.push(new URL(request.url).pathname);
        return HttpResponse.json({ reference_direction: "cost_to_price" });
      }),
    );

    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useMakerSettings(), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seen).toEqual(["/api/v1/maker/settings"]);
  });
});

describe("maker recipe hooks — module gating", () => {
  it("does not fetch when the maker module is disabled", async () => {
    // New behaviour from the useModuleQuery migration: the raw useQuery it
    // replaced had no module gate at all.
    enabledModules.current = [];
    let called = false;
    server.use(
      http.get("*/maker/recipes", () => {
        called = true;
        return HttpResponse.json({
          items: [],
          total: 0,
          limit: 50,
          offset: 0,
          has_more: false,
        });
      }),
    );

    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useMakerRecipeCatalog(), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));
    expect(called).toBe(false);
  });

  it("keeps the id guard on top of the module gate", async () => {
    let called = false;
    server.use(
      http.get("*/maker/recipes/:id", () => {
        called = true;
        return HttpResponse.json({ id: "r1" });
      }),
    );

    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useMakerRecipe(undefined), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));
    expect(called).toBe(false);
  });
});

describe("maker recipe hooks — cache keys", () => {
  it("uses the same key shape the inline arrays used", () => {
    // Guards the migration itself: a changed shape would orphan cached data
    // instead of invalidating it.
    expect(queryKeys.maker.recipesAll).toEqual(["maker", "recipes"]);
    expect(queryKeys.maker.recipeDetail("r1")).toEqual([
      "maker",
      "recipes",
      "detail",
      "r1",
    ]);
    expect(queryKeys.maker.recipeSettings).toEqual([
      "maker",
      "recipes",
      "settings",
    ]);
    expect(queryKeys.maker.recipeCatalog("q", "newest", 0, 50)).toEqual([
      "maker",
      "recipes",
      "catalog",
      "q",
      "newest",
      0,
      50,
    ]);
  });

  it("invalidates recipe caches after a create", async () => {
    server.use(
      http.post("*/maker/recipes", () => HttpResponse.json({ id: "r-new" })),
    );

    const { Wrapper, queryClient } = createWrapper();
    queryClient.setQueryData(queryKeys.maker.recipesAll, { stale: true });
    const spy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useCreateMakerRecipe(), {
      wrapper: Wrapper,
    });
    result.current.mutate({ name: "R" } as never);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // `invalidation.maker` invalidates the whole `["maker"]` prefix, which
    // covers every recipe key.
    expect(spy).toHaveBeenCalledWith({ queryKey: ["maker"] });
  });
});
