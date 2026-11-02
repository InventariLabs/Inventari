import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "@/test/mocks/server";
import { recordRequests } from "@/test/requestLog";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useAddMealPlanEntry,
  useCopyPlanToWeek,
  useCreateMealPlan,
  useCreateShoppingExclusion,
  useDeleteMealPlan,
  useDeleteMealPlanEntry,
  useDeleteShoppingExclusion,
  useGenerateMealPlanShoppingList,
  useMealPlan,
  useMealPlans,
  useShoppingExclusions,
  useUpdateMealPlan,
  useUpdateMealPlanEntry,
} from "./useMealPlans";

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
 * The meal planner's hooks, one endpoint each. A move that does not show at
 * once feels broken, and a move the server refused must not stay on screen.
 */
describe("meal plan reads", () => {
  it.each([
    [
      "useMealPlans",
      () => useMealPlans({ start_date: "2026-10-26", limit: 4 }),
      "/recipes/meal-plans",
      { start_date: "2026-10-26", limit: "4" },
    ],
    ["useMealPlan", () => useMealPlan("p1"), "/recipes/meal-plans/p1", {}],
    [
      "useShoppingExclusions",
      () => useShoppingExclusions(),
      "/recipes/meal-plans/exclusions",
      {},
    ],
  ])("%s asks %s", async (_name, hook, path, query) => {
    const log = recordRequests(() => ({
      items: [],
      has_more: false,
      total: 0,
    }));
    renderHook(hook as () => unknown, { wrapper });
    await waitFor(() => expect(log.length).toBeGreaterThan(0));
    expect(log[0]).toMatchObject({ method: "GET", path, query });
  });

  it("does not ask for a plan nobody named", async () => {
    const log = recordRequests();
    const { result } = renderHook(() => useMealPlan(undefined), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(log).toHaveLength(0);
  });
});

describe("meal plan writes", () => {
  type Case = [
    string,
    () => { mutateAsync: (vars: never) => Promise<unknown> },
    unknown,
    { method: string; path: string; body?: unknown },
  ];
  const cases: Case[] = [
    [
      "useCreateMealPlan",
      useCreateMealPlan,
      { name: "Week" },
      { method: "POST", path: "/recipes/meal-plans", body: { name: "Week" } },
    ],
    [
      "useUpdateMealPlan",
      useUpdateMealPlan,
      { id: "p1", data: { name: "W" } },
      { method: "PUT", path: "/recipes/meal-plans/p1", body: { name: "W" } },
    ],
    [
      "useDeleteMealPlan",
      useDeleteMealPlan,
      "p1",
      { method: "DELETE", path: "/recipes/meal-plans/p1" },
    ],
    [
      "useAddMealPlanEntry",
      useAddMealPlanEntry,
      { planId: "p1", data: { recipe_id: "r1" } },
      {
        method: "POST",
        path: "/recipes/meal-plans/p1/entries",
        body: { recipe_id: "r1" },
      },
    ],
    [
      "useDeleteMealPlanEntry",
      useDeleteMealPlanEntry,
      { planId: "p1", entryId: "e1" },
      { method: "DELETE", path: "/recipes/meal-plans/p1/entries/e1" },
    ],
    [
      "useUpdateMealPlanEntry",
      useUpdateMealPlanEntry,
      { planId: "p1", entryId: "e1", data: { slot: "DINNER" } },
      {
        method: "PUT",
        path: "/recipes/meal-plans/p1/entries/e1",
        body: { slot: "DINNER" },
      },
    ],
    [
      "useGenerateMealPlanShoppingList",
      useGenerateMealPlanShoppingList,
      "p1",
      { method: "POST", path: "/recipes/meal-plans/p1/generate-shopping-list" },
    ],
    [
      "useCopyPlanToWeek",
      useCopyPlanToWeek,
      { planId: "p1", data: { target_start_date: "2026-11-02" } },
      {
        method: "POST",
        path: "/recipes/meal-plans/p1/copy-to",
        body: { target_start_date: "2026-11-02" },
      },
    ],
    [
      "useCreateShoppingExclusion",
      useCreateShoppingExclusion,
      { template_id: "t1" },
      {
        method: "POST",
        path: "/recipes/meal-plans/exclusions",
        body: { template_id: "t1" },
      },
    ],
    [
      "useDeleteShoppingExclusion",
      useDeleteShoppingExclusion,
      "x1",
      { method: "DELETE", path: "/recipes/meal-plans/exclusions/x1" },
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

  it("generating a shopping list refreshes the shopping lists too", async () => {
    recordRequests(() => ({}));
    client.setQueryDefaults(queryKeys.shoppingLists.all, { gcTime: Infinity });
    client.setQueryData(queryKeys.shoppingLists.all, []);
    const { result } = renderHook(() => useGenerateMealPlanShoppingList(), {
      wrapper,
    });
    await act(() => result.current.mutateAsync("p1"));
    expect(
      client.getQueryState(queryKeys.shoppingLists.all)?.isInvalidated,
    ).toBe(true);
  });
});

describe("useUpdateMealPlanEntry optimistic move", () => {
  const plan = {
    id: "p1",
    entries: [
      {
        id: "e1",
        date: "2026-10-26",
        slot: "LUNCH",
        order: 0,
        servings: 2,
        notes: null,
      },
      {
        id: "e2",
        date: "2026-10-26",
        slot: "LUNCH",
        order: 1,
        servings: 2,
        notes: "keep",
      },
    ],
  };
  const seedPlan = () => {
    client.setQueryDefaults(queryKeys.mealPlans.detail("p1"), {
      gcTime: Infinity,
    });
    client.setQueryData(queryKeys.mealPlans.detail("p1"), plan);
  };
  const read = () =>
    client.getQueryData<typeof plan>(queryKeys.mealPlans.detail("p1"))!;

  it("moves only the named entry, and keeps the fields the move did not mention", async () => {
    let seenWhileInFlight: typeof plan | undefined;
    server.use(
      http.put("/api/v1/recipes/meal-plans/p1/entries/e1", async () => {
        seenWhileInFlight = read();
        return HttpResponse.json({});
      }),
    );
    seedPlan();
    const { result } = renderHook(() => useUpdateMealPlanEntry(), { wrapper });
    await act(() =>
      result.current.mutateAsync({
        planId: "p1",
        entryId: "e1",
        data: { slot: "DINNER", date: "2026-10-27" },
      }),
    );
    expect(seenWhileInFlight?.entries[0]).toMatchObject({
      slot: "DINNER",
      date: "2026-10-27",
      order: 0,
      servings: 2,
    });
    expect(seenWhileInFlight?.entries[1]).toEqual(plan.entries[1]);
  });

  it("puts the entry back where it was when the server refuses the move", async () => {
    server.use(
      http.put("/api/v1/recipes/meal-plans/p1/entries/e1", () =>
        HttpResponse.json({ detail: "no" }, { status: 500 }),
      ),
    );
    seedPlan();
    const { result } = renderHook(() => useUpdateMealPlanEntry(), { wrapper });
    await act(async () => {
      await result.current
        .mutateAsync({ planId: "p1", entryId: "e1", data: { slot: "DINNER" } })
        .catch(() => undefined);
    });
    expect(read().entries[0].slot).toBe("LUNCH");
  });

  it("moves nothing in the cache when the plan was never loaded", async () => {
    recordRequests(() => ({}));
    const { result } = renderHook(() => useUpdateMealPlanEntry(), { wrapper });
    await act(() =>
      result.current.mutateAsync({
        planId: "p1",
        entryId: "e1",
        data: { slot: "DINNER" },
      }),
    );
    expect(
      client.getQueryData(queryKeys.mealPlans.detail("p1")),
    ).toBeUndefined();
  });
});
