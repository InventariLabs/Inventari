import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { recordRequests } from "@/test/requestLog";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useAddRecipeToCollection,
  useAddToShoppingList,
  useAvailableRecipes,
  useBulkDeleteRecipes,
  useBulkTagRecipes,
  useCreateCookingHistory,
  useCreateRecipe,
  useCreateRecipeCollection,
  useDeleteRecipe,
  useDeleteRecipeCollection,
  useDeleteRecipeImage,
  useDeleteTag,
  useDuplicateRecipe,
  useExportRecipe,
  useLinkIngredientTemplate,
  useMergeTags,
  usePatchCookingHistory,
  usePreviewImport,
  useRecipe,
  useRecipeAvailability,
  useRecipeCollections,
  useRecipeCost,
  useRecipeHistory,
  useRecipeNutrition,
  useRecipeTags,
  useRecipes,
  useSetTagColor,
  useToggleRecipeFavorite,
  useUpdateRecipe,
  useUpdateRecipeCollection,
} from "./useRecipes";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const modules = vi.hoisted(() => ({ enabled: true }));
vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    isLoading: false,
    isModuleEnabled: () => modules.enabled,
  }),
}));

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

/** The harness collects a query the moment nothing observes it (gcTime 0);
 *  with no component mounted, the per-key override keeps a seeded one alive. */
const seed = (key: readonly unknown[], data: unknown) => {
  client.setQueryDefaults(key, { gcTime: Infinity });
  client.setQueryData(key, data);
};

beforeEach(() => {
  vi.clearAllMocks();
  modules.enabled = true;
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
});

/**
 * Each hook is the contract between a screen and one endpoint: which method,
 * which path, which body. A swapped path or a dropped field sends the
 * server something other than what the screen showed.
 */
describe("recipe reads", () => {
  it.each([
    [
      "useRecipes",
      () => useRecipes({ search: "soup", limit: 10 }),
      "/recipes",
      { search: "soup", limit: "10" },
    ],
    [
      "useAvailableRecipes",
      () => useAvailableRecipes({ min_match: 80 }),
      "/recipes/available",
      { min_match: "80" },
    ],
    ["useRecipe", () => useRecipe("r1"), "/recipes/r1", {}],
    [
      "useRecipeAvailability",
      () => useRecipeAvailability("r1", 4),
      "/recipes/r1/availability",
      { servings: "4" },
    ],
    [
      "useRecipeNutrition",
      () => useRecipeNutrition("r1", 2),
      "/recipes/r1/nutrition",
      { servings: "2" },
    ],
    [
      "useRecipeHistory",
      () => useRecipeHistory("r1"),
      "/recipes/r1/history",
      {},
    ],
    [
      "useRecipeCost",
      () => useRecipeCost("r1", 3),
      "/recipes/r1/cost",
      { servings: "3" },
    ],
    [
      "useRecipeTags",
      () => useRecipeTags({ is_favorite: true }),
      "/recipes/tags",
      { is_favorite: "true" },
    ],
    [
      "useRecipeCollections",
      () => useRecipeCollections(),
      "/recipes/collections",
      {},
    ],
  ])("%s asks %s with the right query", async (_name, hook, path, query) => {
    const log = recordRequests(() => ({
      items: [],
      total: 0,
      has_more: false,
    }));
    renderHook(hook as () => unknown, { wrapper });
    await waitFor(() => expect(log.length).toBeGreaterThan(0));
    expect(log[0]).toMatchObject({ method: "GET", path, query });
  });

  it.each([
    ["useRecipe", () => useRecipe(undefined)],
    ["useRecipeAvailability", () => useRecipeAvailability(undefined)],
    ["useRecipeNutrition", () => useRecipeNutrition(undefined)],
    ["useRecipeHistory", () => useRecipeHistory(undefined)],
    ["useRecipeCost", () => useRecipeCost(undefined)],
  ])("%s does not ask for a recipe nobody named", async (_name, hook) => {
    const log = recordRequests();
    const { result } = renderHook(hook as () => { fetchStatus: string }, {
      wrapper,
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(log).toHaveLength(0);
  });

  it("does not read recipes of an organization that has the module off", async () => {
    modules.enabled = false;
    const log = recordRequests();
    const { result } = renderHook(() => useRecipes(), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(log).toHaveLength(0);
  });

  it("unwraps the history list from its envelope", async () => {
    recordRequests(() => ({ items: [{ id: "h1" }] }));
    const { result } = renderHook(() => useRecipeHistory("r1"), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual([{ id: "h1" }]));
  });
});

type Case = [
  name: string,
  hook: () => { mutateAsync: (vars: never) => Promise<unknown> },
  vars: unknown,
  expected: { method: string; path: string; body?: unknown; query?: unknown },
];

describe("recipe writes", () => {
  const cases: Case[] = [
    [
      "useCreateRecipe",
      useCreateRecipe,
      { name: "Soup" },
      { method: "POST", path: "/recipes", body: { name: "Soup" } },
    ],
    [
      "useDuplicateRecipe",
      useDuplicateRecipe,
      "r1",
      { method: "POST", path: "/recipes/r1/duplicate" },
    ],
    [
      "useBulkDeleteRecipes",
      useBulkDeleteRecipes,
      ["r1", "r2"],
      {
        method: "POST",
        path: "/recipes/bulk-delete",
        body: { recipe_ids: ["r1", "r2"] },
      },
    ],
    [
      "useBulkTagRecipes",
      useBulkTagRecipes,
      { recipeIds: ["r1"], tags: ["quick"] },
      {
        method: "POST",
        path: "/recipes/bulk-tag",
        body: { recipe_ids: ["r1"], tags: ["quick"] },
      },
    ],
    [
      "useCreateRecipeCollection",
      useCreateRecipeCollection,
      { name: "Week" },
      { method: "POST", path: "/recipes/collections", body: { name: "Week" } },
    ],
    [
      "useUpdateRecipeCollection",
      useUpdateRecipeCollection,
      { id: "c1", data: { name: "Wk" } },
      { method: "PUT", path: "/recipes/collections/c1", body: { name: "Wk" } },
    ],
    [
      "useDeleteRecipeCollection",
      useDeleteRecipeCollection,
      "c1",
      { method: "DELETE", path: "/recipes/collections/c1" },
    ],
    [
      "useAddRecipeToCollection",
      useAddRecipeToCollection,
      { collectionId: "c1", recipeId: "r1" },
      {
        method: "POST",
        path: "/recipes/collections/c1/recipes",
        body: { recipe_id: "r1" },
      },
    ],
    [
      "useUpdateRecipe",
      useUpdateRecipe,
      { id: "r1", data: { name: "New" } },
      { method: "PUT", path: "/recipes/r1", body: { name: "New" } },
    ],
    [
      "useDeleteRecipe",
      useDeleteRecipe,
      "r1",
      { method: "DELETE", path: "/recipes/r1" },
    ],
    [
      "useLinkIngredientTemplate",
      () => useLinkIngredientTemplate("r1"),
      { ingredientId: "i1", templateId: "t1" },
      {
        method: "POST",
        path: "/recipes/r1/ingredients/i1/link-template",
        body: { template_id: "t1" },
      },
    ],
    [
      "useCreateCookingHistory",
      () => useCreateCookingHistory("r1"),
      { servings: 3, sessionId: "s1" },
      {
        method: "POST",
        path: "/recipes/r1/history",
        body: { servings: 3, session_id: "s1" },
      },
    ],
    [
      "usePatchCookingHistory",
      () => usePatchCookingHistory("r1"),
      { sessionId: "s1", data: { rating: 5 } },
      { method: "PATCH", path: "/recipes/r1/history/s1", body: { rating: 5 } },
    ],
    [
      "useAddToShoppingList",
      () => useAddToShoppingList("r1"),
      { servings: 2 },
      {
        method: "POST",
        path: "/recipes/r1/add-to-shopping-list",
        body: { servings: 2 },
      },
    ],
    [
      "useDeleteRecipeImage",
      useDeleteRecipeImage,
      "r1",
      { method: "DELETE", path: "/recipes/r1/image" },
    ],
    [
      "useSetTagColor",
      useSetTagColor,
      { name: "a/b", color: "red" },
      {
        method: "PATCH",
        path: "/recipes/tags/a%2Fb/color",
        body: { color: "red" },
      },
    ],
    [
      "useMergeTags",
      useMergeTags,
      { source_tags: ["a"], target_tag: "b" },
      {
        method: "POST",
        path: "/recipes/tags/merge",
        body: { source_tags: ["a"], target_tag: "b" },
      },
    ],
    [
      "useDeleteTag",
      useDeleteTag,
      "a b",
      { method: "DELETE", path: "/recipes/tags/a%20b" },
    ],
    [
      "usePreviewImport",
      usePreviewImport,
      { url: "https://x.test/r" },
      {
        method: "POST",
        path: "/recipes/import/preview",
        body: { url: "https://x.test/r" },
      },
    ],
    [
      "useExportRecipe",
      useExportRecipe,
      { id: "r1", format: "schema_org" },
      {
        method: "GET",
        path: "/recipes/r1/export",
        query: { format: "schema_org" },
      },
    ],
  ];

  it.each(cases)(
    "%s sends the request its screen promised",
    async (_n, hook, vars, expected) => {
      const log = recordRequests();
      const { result } = renderHook(hook, { wrapper });
      await act(() => result.current.mutateAsync(vars as never));
      expect(log).toHaveLength(1);
      expect(log[0]).toMatchObject(expected);
    },
  );

  it("drops the recipe caches after a write, so the list is read again", async () => {
    recordRequests();
    seed(queryKeys.recipes.all(), { items: [], total: 0 });
    const { result } = renderHook(() => useDeleteRecipe(), { wrapper });
    await act(() => result.current.mutateAsync("r1"));
    expect(client.getQueryState(queryKeys.recipes.all())?.isInvalidated).toBe(
      true,
    );
  });

  it("refreshes the tag counts after merging or deleting tags", async () => {
    recordRequests();
    seed(queryKeys.recipes.tags, []);
    const merge = renderHook(() => useMergeTags(), { wrapper });
    await act(() =>
      merge.result.current.mutateAsync({
        source_tags: ["a"],
        target_tag: "b",
      } as never),
    );
    expect(client.getQueryState(queryKeys.recipes.tags)?.isInvalidated).toBe(
      true,
    );
  });

  it("refreshes the history after a cook is recorded", async () => {
    recordRequests();
    seed(queryKeys.recipes.history("r1"), []);
    const { result } = renderHook(() => useCreateCookingHistory("r1"), {
      wrapper,
    });
    await act(() => result.current.mutateAsync({}));
    expect(
      client.getQueryState(queryKeys.recipes.history("r1"))?.isInvalidated,
    ).toBe(true);
  });

  it("sends no servings or session when a cook is recorded without them", async () => {
    const log = recordRequests();
    const { result } = renderHook(() => useCreateCookingHistory("r1"), {
      wrapper,
    });
    await act(() => result.current.mutateAsync(undefined));
    expect(log[0].body).toEqual({});
  });
});

describe("useToggleRecipeFavorite", () => {
  const recipe = (id: string, fav: boolean) => ({ id, is_favorite: fav });

  it("flips the star in a list page and in a plain array at once, and leaves other shapes alone", async () => {
    recordRequests();
    seed(queryKeys.recipes.all({ limit: 1 }), {
      items: [recipe("r1", false), recipe("r2", false)],
      total: 2,
    });
    seed(queryKeys.recipes.available({ min_match: 1 }), [recipe("r1", false)]);
    const odd = { something: "else" };
    seed([...queryKeys.recipes.all(), "odd"], odd);
    const { result } = renderHook(() => useToggleRecipeFavorite(), { wrapper });

    await act(() =>
      result.current.mutateAsync({ recipeId: "r1", newValue: true }),
    );

    // The optimistic write is what the reader saw before the request returned;
    // the invalidation afterwards only marks it stale.
    const page = client.getQueryData<{
      items: { id: string; is_favorite: boolean }[];
    }>(queryKeys.recipes.all({ limit: 1 }));
    expect(page?.items.map((r) => r.is_favorite)).toEqual([true, false]);
    expect(
      client.getQueryData<{ is_favorite: boolean }[]>(
        queryKeys.recipes.available({ min_match: 1 }),
      )?.[0].is_favorite,
    ).toBe(true);
    expect(client.getQueryData([...queryKeys.recipes.all(), "odd"])).toBe(odd);
  });

  it("puts the star back when the save is refused", async () => {
    const log: string[] = [];
    recordRequests((req) => {
      log.push(req.method);
      return undefined;
    });
    seed(queryKeys.recipes.all(), { items: [recipe("r1", false)], total: 1 });
    const { server } = await import("@/test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.put("/api/v1/recipes/r1", () =>
        HttpResponse.json({ detail: "no" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useToggleRecipeFavorite(), { wrapper });
    await act(async () => {
      await result.current
        .mutateAsync({ recipeId: "r1", newValue: true })
        .catch(() => undefined);
    });
    const page = client.getQueryData<{ items: { is_favorite: boolean }[] }>(
      queryKeys.recipes.all(),
    );
    expect(page?.items[0].is_favorite).toBe(false);
  });
});
