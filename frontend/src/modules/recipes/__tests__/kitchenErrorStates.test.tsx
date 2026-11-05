import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import MealPlannerPage from "@/modules/recipes/pages/MealPlannerPage";
import MealPlanDetailPage from "@/modules/recipes/pages/MealPlanDetailPage";
import IngredientDefaultsPage from "@/modules/recipes/pages/IngredientDefaultsPage";
import ShoppingListsPage from "@/modules/shopping_lists/pages/ShoppingListsPage";
import ProductionListPage from "@/modules/maker/pages/ProductionListPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["recipes", "shopping_lists", "maker"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

/**
 * The kitchen screens made the same claim the equipment and trade ones did.
 *
 * Four plans, five shopping lists and twelve production runs were reported as
 * none, because the failed read reached the empty state through a default
 * empty array. The ingredient table did not even manage that: `data` was
 * undefined, so neither the empty branch nor the row map matched and the screen
 * rendered its header row over nothing at all -- no message, no retry, no way
 * to tell an outage from a table someone had never filled in.
 */
function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      <div data-testid="header-title">{data.title}</div>
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderAt(path: string, route: string, element: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <PageHeaderHost>
          <Routes>
            <Route path={route} element={element} />
          </Routes>
        </PageHeaderHost>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const ACCOUNT = [
  "recipes:read",
  "recipes:write",
  "shopping_lists:read",
  "shopping_lists:write",
  "maker:read",
  "maker:write",
];

const fails = (path: string) =>
  http.get(path, () => new HttpResponse(null, { status: 500 }));

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.get("/api/v1/recipes/meal-plans", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/recipes/ingredient-defaults", () =>
      HttpResponse.json({
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
        has_more: false,
      }),
    ),
    http.get("/api/v1/shopping-lists", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/maker/production/orders", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
  );
  signInWith(ACCOUNT);
});

afterEach(() => {
  signOut();
});

async function expectRetryOffered() {
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(
    await screen.findByRole("button", { name: /try again|retry/i }),
  ).toBeInTheDocument();
}

describe("Kitchen — a failed read stops reporting an empty kitchen", () => {
  it("says the meal plans could not be read", async () => {
    server.use(fails("/api/v1/recipes/meal-plans"));
    renderAt(
      "/recipes/meal-planner",
      "/recipes/meal-planner",
      <MealPlannerPage />,
    );

    await expectRetryOffered();
    expect(screen.queryByText(/no meal plans yet/i)).not.toBeInTheDocument();
  });

  it("still says there are no meal plans when there are none", async () => {
    renderAt(
      "/recipes/meal-planner",
      "/recipes/meal-planner",
      <MealPlannerPage />,
    );

    expect(await screen.findByText(/no meal plans yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says the shopping lists could not be read", async () => {
    server.use(fails("/api/v1/shopping-lists"));
    renderAt("/shopping-lists", "/shopping-lists", <ShoppingListsPage />);

    await expectRetryOffered();
    expect(
      screen.queryByText(/create your first shopping list/i),
    ).not.toBeInTheDocument();
  });

  it("says the production runs could not be read", async () => {
    server.use(fails("/api/v1/maker/production/orders"));
    renderAt("/maker/production", "/maker/production", <ProductionListPage />);

    await expectRetryOffered();
    expect(
      screen.queryByText(/schedule a production run/i),
    ).not.toBeInTheDocument();
  });

  it("does not leave the ingredient table as a header row over nothing", async () => {
    server.use(fails("/api/v1/recipes/ingredient-defaults"));
    renderAt(
      "/recipes/ingredient-data",
      "/recipes/ingredient-data",
      <IngredientDefaultsPage />,
    );

    await expectRetryOffered();
  });

  it("withholds Export while the ingredient table has not been read", async () => {
    server.use(fails("/api/v1/recipes/ingredient-defaults"));
    renderAt(
      "/recipes/ingredient-data",
      "/recipes/ingredient-data",
      <IngredientDefaultsPage />,
    );

    await expectRetryOffered();
    expect(screen.getByRole("button", { name: /export/i })).toBeDisabled();
  });

  it("offers Export once the table is there", async () => {
    server.use(
      http.get("/api/v1/recipes/ingredient-defaults", () =>
        HttpResponse.json({
          items: [
            {
              id: "def-1",
              name: "Apple",
              name_normalized: "apple",
              lang: "en",
              organization_id: null,
              kcal: 52,
              protein: 0.3,
              fat: 0.2,
              carbs: 14,
              fiber: 2.4,
              sugar: 10,
              salt: 0,
              source: "system",
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
    );
    renderAt(
      "/recipes/ingredient-data",
      "/recipes/ingredient-data",
      <IngredientDefaultsPage />,
    );

    expect(await screen.findByText(/apple/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export/i })).toBeEnabled();
  });
});

describe("Kitchen — an empty ingredient dictionary names its language", () => {
  it("says the language has no entries and offers add/import, not a failed search", async () => {
    renderAt(
      "/recipes/ingredient-data",
      "/recipes/ingredient-data",
      <IngredientDefaultsPage />,
    );

    // 83 English rows, 85 Polish ones, zero elsewhere: for a de/fr/es
    // reader the empty table read as "nothing was found", a failed search,
    // when the truth is "this dictionary has not been filled yet".
    expect(
      await screen.findByText(/has no entries for english yet/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /import csv/i }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /add override/i }).length,
    ).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/no ingredients found/i)).toBeNull();
    // The hint says what really happens — names are matched across the other
    // languages' entries — and never claims a fallback to the language it
    // is written in.
    expect(
      screen.getByText(/matching entries in other languages/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/fall back to english/i)).toBeNull();
  });

  it("keeps the search answer for a search that finds nothing", async () => {
    const user = userEvent.setup();
    renderAt(
      "/recipes/ingredient-data",
      "/recipes/ingredient-data",
      <IngredientDefaultsPage />,
    );

    await screen.findByText(/has no entries for english yet/i);
    await user.type(
      screen.getByPlaceholderText(/search ingredients/i),
      "zzz-nothing",
    );
    expect(
      await screen.findByText(/no ingredients found/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/has no entries for english/i)).toBeNull();
  });
});

describe("Kitchen — a detail header names only a record it has", () => {
  it("does not call a plan unnamed when the plan could not be read", async () => {
    server.use(fails("/api/v1/recipes/meal-plans/plan-1"));
    renderAt(
      "/recipes/meal-planner/plan-1",
      "/recipes/meal-planner/:id",
      <MealPlanDetailPage />,
    );

    await screen.findByRole("alert");
    expect(screen.getByTestId("header-title")).not.toHaveTextContent(
      /unnamed plan/i,
    );
  });

  it("still calls a plan unnamed when the plan arrived without a name", async () => {
    server.use(
      http.get("/api/v1/recipes/meal-plans/plan-1", () =>
        HttpResponse.json({
          id: "plan-1",
          name: "",
          start_date: "2026-08-24",
          end_date: "2026-08-24",
          enabled_slots: ["BREAKFAST", "LUNCH", "DINNER"],
          default_servings: 2,
          shopping_list_id: null,
          notes: null,
          entries: [],
          daily_nutrition_summary: [],
        }),
      ),
    );
    renderAt(
      "/recipes/meal-planner/plan-1",
      "/recipes/meal-planner/:id",
      <MealPlanDetailPage />,
    );

    await waitFor(() =>
      expect(screen.getByTestId("header-title")).toHaveTextContent(
        /unnamed plan/i,
      ),
    );
  });
});
