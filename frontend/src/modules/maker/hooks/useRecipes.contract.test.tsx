import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { recordRequests } from "@/test/requestLog";
import {
  useAddBomLineToRecipe,
  useAddCostLine,
  useCreateMakerRecipe,
  useDeleteBomLine,
  useDeleteCostLine,
  useDeleteMakerRecipe,
  useMakerRecipe,
  useMakerRecipeAvailability,
  useMakerRecipeCatalog,
  useMakerSettings,
  useUpdateBomLine,
  useUpdateCostLine,
  useUpdateMakerRecipe,
  useUpdateMakerSettings,
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

beforeEach(() => {
  modules.enabled = true;
  client = new QueryClient();
});

/**
 * The formula (recipe) screens of the maker module: each hook is one endpoint,
 * and an organization without the module must not call any of them.
 */
describe("maker formula reads", () => {
  it.each([
    [
      "useMakerRecipeCatalog",
      () => useMakerRecipeCatalog("jam", "name", 10, 20),
      "/maker/recipes",
      { search: "jam", sort: "name", skip: "10", limit: "20" },
    ],
    [
      "useMakerRecipeCatalog defaults",
      () => useMakerRecipeCatalog(),
      "/maker/recipes",
      { sort: "newest", skip: "0", limit: "50" },
    ],
    ["useMakerRecipe", () => useMakerRecipe("r1"), "/maker/recipes/r1", {}],
    ["useMakerSettings", () => useMakerSettings(), "/maker/settings", {}],
    [
      "useMakerRecipeAvailability",
      () => useMakerRecipeAvailability("r1", "3", "loc1"),
      "/maker/recipes/r1/availability",
      { batches: "3", location_id: "loc1" },
    ],
  ])("%s asks %s", async (_name, hook, path, query) => {
    const log = recordRequests(() => ({}));
    renderHook(hook as () => unknown, { wrapper });
    await waitFor(() => expect(log.length).toBeGreaterThan(0));
    expect(log[0]).toMatchObject({ method: "GET", path, query });
  });

  it.each([
    ["useMakerRecipe", () => useMakerRecipe(undefined)],
    ["useMakerRecipeAvailability", () => useMakerRecipeAvailability(undefined)],
  ])("%s waits for a formula to be named", async (_name, hook) => {
    const log = recordRequests();
    const { result } = renderHook(hook as () => { fetchStatus: string }, {
      wrapper,
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(log).toHaveLength(0);
  });

  it("asks nothing of an organization that has the module off", async () => {
    modules.enabled = false;
    const log = recordRequests();
    const { result } = renderHook(() => useMakerSettings(), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(log).toHaveLength(0);
  });
});

describe("maker formula writes", () => {
  type Case = [
    string,
    () => { mutateAsync: (vars: never) => Promise<unknown> },
    unknown,
    { method: string; path: string; body?: unknown },
  ];
  const cases: Case[] = [
    [
      "useCreateMakerRecipe",
      useCreateMakerRecipe,
      { name: "Jam" },
      { method: "POST", path: "/maker/recipes", body: { name: "Jam" } },
    ],
    [
      "useUpdateMakerRecipe",
      useUpdateMakerRecipe,
      { recipeId: "r1", data: { name: "J" } },
      { method: "PATCH", path: "/maker/recipes/r1", body: { name: "J" } },
    ],
    [
      "useDeleteMakerRecipe",
      useDeleteMakerRecipe,
      "r1",
      { method: "DELETE", path: "/maker/recipes/r1" },
    ],
    [
      "useAddCostLine",
      useAddCostLine,
      { recipeId: "r1", data: { label: "gas" } },
      {
        method: "POST",
        path: "/maker/recipes/r1/cost-lines",
        body: { label: "gas" },
      },
    ],
    [
      "useUpdateCostLine",
      useUpdateCostLine,
      { recipeId: "r1", lineId: "c1", data: { label: "g" } },
      {
        method: "PATCH",
        path: "/maker/recipes/r1/cost-lines/c1",
        body: { label: "g" },
      },
    ],
    [
      "useDeleteCostLine",
      useDeleteCostLine,
      { recipeId: "r1", lineId: "c1" },
      { method: "DELETE", path: "/maker/recipes/r1/cost-lines/c1" },
    ],
    [
      "useAddBomLineToRecipe",
      useAddBomLineToRecipe,
      { recipeId: "r1", data: { child_template_id: "t2" } },
      {
        method: "POST",
        path: "/maker/recipes/r1/bom-lines",
        body: { child_template_id: "t2" },
      },
    ],
    [
      "useUpdateBomLine",
      useUpdateBomLine,
      { recipeId: "r1", lineId: "b1", data: { qty_per_batch: "2" } },
      {
        method: "PATCH",
        path: "/maker/recipes/r1/bom-lines/b1",
        body: { qty_per_batch: "2" },
      },
    ],
    [
      "useDeleteBomLine",
      useDeleteBomLine,
      { recipeId: "r1", lineId: "b1" },
      { method: "DELETE", path: "/maker/recipes/r1/bom-lines/b1" },
    ],
    [
      "useUpdateMakerSettings",
      useUpdateMakerSettings,
      { currency: "EUR" },
      { method: "PATCH", path: "/maker/settings", body: { currency: "EUR" } },
    ],
  ];

  it.each(cases)(
    "%s sends the request its screen promised",
    async (_n, hook, vars, expected) => {
      const log = recordRequests(() => ({}));
      const { result } = renderHook(hook, { wrapper });
      await act(() => result.current.mutateAsync(vars as never));
      expect(log).toHaveLength(1);
      expect(log[0]).toMatchObject(expected);
    },
  );

  it("hands the saved settings back to the caller", async () => {
    recordRequests(() => ({ currency: "EUR" }));
    const { result } = renderHook(() => useUpdateMakerSettings(), { wrapper });
    await act(() => result.current.mutateAsync({ currency: "EUR" } as never));
    expect(result.current.data).toEqual({ currency: "EUR" });
  });
});
