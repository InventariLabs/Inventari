import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useState, useCallback } from "react";
import RecipeDetailPage from "./RecipeDetailPage";
import type { MakerRecipe } from "@/modules/maker/types/maker";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from "sonner";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";

const deleteMutate = vi.fn();
const updateMutate = vi.fn();

let currentRecipe: MakerRecipe | undefined;
let currentCanManage = true;

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => currentCanManage,
}));

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerRecipe: () => ({
    data: currentRecipe,
    isLoading: false,
    error: undefined,
    refetch: vi.fn(),
  }),
  useDeleteMakerRecipe: () => ({ mutate: deleteMutate, isPending: false }),
  useUpdateMakerRecipe: () => ({ mutate: updateMutate, isPending: false }),
}));

vi.mock("@/modules/maker/components/AvailabilityBadge", () => ({
  AvailabilityBadge: () => <div data-testid="maker-recipe-availability" />,
}));

vi.mock("./tabs/CompositionTab", () => ({
  CompositionTab: () => <div />,
}));
vi.mock("./tabs/CostResultTab", () => ({
  CostResultTab: () => <div />,
}));
vi.mock("./tabs/HistoryTab", () => ({ HistoryTab: () => <div /> }));

const baseRecipe: MakerRecipe = {
  id: "rec-1",
  organization_id: "org-1",
  output_template_id: "tpl-jar",
  name: "Jar of jam",
  batch_yield_qty: "1",
  batch_yield_uom_id: null,
  process_steps: null,
  reference_price: null,
  is_default: false,
  source_recipe_id: null,
  source_snapshot_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  output_template_name: "Jar",
  batch_yield_uom_symbol: "pcs",
  cost_lines: [],
  lines: [],
  estimated_unit_cost: null,
};

// The set-default button lives in the header's actions slot, which a stubbed
// context would swallow — render what the page hands to setHeader, so the
// tests see the row the reader gets.
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function HeaderHarness({ children }: { children: React.ReactNode }) {
    const [actions, setActions] = useState<React.ReactNode>(null);
    const [subtitle, setSubtitle] = useState<string | undefined>(undefined);
    // Stable, as the real shell's is: a fresh identity per render would make
    // the page's header effect fire every render and loop this harness.
    const setHeader = useCallback(
      (config: { actions?: React.ReactNode; subtitle?: string }) => {
        setActions(config.actions ?? null);
        setSubtitle(config.subtitle);
      },
      [],
    );
    return (
      <PageHeaderContext.Provider value={{ data: {}, setHeader }}>
        {children}
        <div data-testid="header-actions">{actions}</div>
        <div data-testid="header-subtitle">{subtitle}</div>
      </PageHeaderContext.Provider>
    );
  }
  return render(
    <HeaderHarness>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/maker/recipes/rec-1"]}>
          <Routes>
            <Route
              path="/maker/recipes/:recipeId"
              element={<RecipeDetailPage />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </HeaderHarness>,
  );
}

describe("RecipeDetailPage — the default formula is a choice, not a birthright", () => {
  beforeEach(() => {
    currentRecipe = { ...baseRecipe };
    currentCanManage = true;
    vi.clearAllMocks();
  });

  it("names the product under the title only when it is a different name", () => {
    currentRecipe = { ...baseRecipe, name: "Jar", output_template_name: "Jar" };
    const { unmount } = renderPage();
    expect(screen.getByTestId("header-subtitle")).toBeEmptyDOMElement();
    unmount();

    currentRecipe = {
      ...baseRecipe,
      name: "Jar, large batch",
      output_template_name: "Jar",
    };
    renderPage();
    expect(screen.getByTestId("header-subtitle")).toHaveTextContent("Jar");
  });

  it("leaves the recipe's name to the page title and keeps the card's own facts", () => {
    currentRecipe = { ...baseRecipe, is_default: true };
    renderPage();
    // The title is the shell's header; nothing in the page body repeats it.
    expect(screen.queryByText("Jar of jam")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.getByText(/default/i)).toBeInTheDocument();
    expect(screen.getByText(/1/)).toBeInTheDocument();
  });

  it("offers Set as default on a formula that is not the default", () => {
    currentRecipe = { ...baseRecipe, is_default: false };
    renderPage();

    expect(screen.getByTestId("maker-recipe-set-default")).toBeInTheDocument();
  });

  it("demotes nothing visually: the default formula offers no such button", () => {
    currentRecipe = { ...baseRecipe, is_default: true };
    renderPage();

    expect(
      screen.queryByTestId("maker-recipe-set-default"),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/default/i)).toBeInTheDocument();
  });

  it("sends is_default: true through the update mutation and confirms", () => {
    currentRecipe = { ...baseRecipe, is_default: false };
    renderPage();

    fireEvent.click(screen.getByTestId("maker-recipe-set-default"));

    expect(updateMutate).toHaveBeenCalledWith(
      { recipeId: "rec-1", data: { is_default: true } },
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );
  });

  it("keeps the choice away from an account that only runs the floor", () => {
    currentCanManage = false;
    renderPage();

    expect(
      screen.queryByTestId("maker-recipe-set-default"),
    ).not.toBeInTheDocument();
  });
});

describe("RecipeDetailPage — toast speaks for the set-default result", () => {
  beforeEach(() => {
    currentRecipe = { ...baseRecipe };
    currentCanManage = true;
    vi.clearAllMocks();
  });

  it("confirms with the success toast the mutation was given", () => {
    renderPage();

    fireEvent.click(screen.getByTestId("maker-recipe-set-default"));
    const call = updateMutate.mock.calls[0];
    call?.[1]?.onSuccess?.();

    expect(toast.success).toHaveBeenCalled();
  });
});
