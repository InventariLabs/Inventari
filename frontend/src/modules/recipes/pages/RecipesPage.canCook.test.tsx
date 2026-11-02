import React, { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import RecipesPage from "./RecipesPage";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";

/**
 * "I can cook" has to mean it.
 *
 * The tab passed anything at least half covered, so a recipe whose own card
 * read "3 of 4 in stock" stood under a heading promising it could be cooked
 * right now. The two readings contradicted each other on the same card, and
 * the one people act on is the heading — they stop checking the cupboard.
 *
 * The near misses are worth keeping, so they are a second chip with its own
 * name and its own count, rather than folded into the first.
 */

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["recipes"],
    isModuleEnabled: (name: string) => name === "recipes",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

const recipe = (
  name: string,
  available: number,
  total: number,
  missing: string[],
) => ({
  id: name.toLowerCase().replace(/ /g, "-"),
  name,
  description: null,
  servings: 2,
  prep_time_minutes: null,
  image_url: null,
  tags: [],
  is_favorite: false,
  created_at: "2026-01-01T00:00:00Z",
  source_url: null,
  ingredients_total: total,
  ingredients_linked: total,
  ingredients_available: available,
  missing_names: missing,
  match_percentage: available / total,
});

const cookable = recipe("Scrambled Eggs", 3, 3, []);
const nearlyThere = recipe("Breakfast Pancakes", 3, 4, ["White sugar"]);

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => {
    const [headerData, setHeaderData] = useState<{
      title?: string;
      subtitle?: string;
      actions?: React.ReactNode;
    }>({});
    return (
      <PageHeaderContext.Provider
        value={{ data: headerData, setHeader: setHeaderData }}
      >
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>{children}</BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>
    );
  };
};

const openTheCookTab = async () => {
  render(<RecipesPage />, { wrapper: createWrapper() });
  await waitFor(() => {
    expect(screen.getByText("I can cook")).toBeInTheDocument();
  });
  await userEvent.click(screen.getByText("I can cook"));
};

describe("RecipesPage — the cook tab keeps its promise", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/recipes/available", () =>
        HttpResponse.json(onePage([cookable, nearlyThere])),
      ),
    );
  });

  it("leaves out a recipe that is three ingredients of four", async () => {
    await openTheCookTab();

    await waitFor(() => {
      expect(screen.getByText("Scrambled Eggs")).toBeInTheDocument();
    });
    expect(screen.queryByText("Breakfast Pancakes")).not.toBeInTheDocument();
  });

  it("says how many are nearly there, and shows them when asked", async () => {
    await openTheCookTab();

    await waitFor(() => {
      expect(screen.getByText("Ready to cook (1)")).toBeInTheDocument();
    });
    const almost = screen.getByText("Nearly there (1)");

    await userEvent.click(almost);

    await waitFor(() => {
      expect(screen.getByText("Breakfast Pancakes")).toBeInTheDocument();
    });
    expect(screen.queryByText("Scrambled Eggs")).not.toBeInTheDocument();
  });
});

describe("RecipesPage — an empty ready list names the near miss", () => {
  it("says which ingredient the only recipe is missing", async () => {
    // "No recipes available right now" over a recipe one ingredient short
    // read as an empty cupboard; the sentence can name the gap instead.
    server.use(
      // The whole list tells the page the recipe's ingredients are linked;
      // without it the empty state reads as "nothing linked to stock".
      http.get("/api/v1/recipes", () =>
        HttpResponse.json({ items: [nearlyThere], total: 1 }),
      ),
      http.get("/api/v1/recipes/available", () =>
        HttpResponse.json(onePage([nearlyThere])),
      ),
    );

    await openTheCookTab();

    await waitFor(() => {
      expect(
        screen.getByText('"Breakfast Pancakes" is only missing White sugar.'),
      ).toBeInTheDocument();
    });
  });
});
