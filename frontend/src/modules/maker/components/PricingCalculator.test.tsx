import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import { PricingCalculator } from "@/modules/maker/components/PricingCalculator";

function renderWithQuery(node: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>{node}</QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("PricingCalculator", () => {
  it("names the margin controls — the slider and the field mirroring it", async () => {
    server.use(
      http.get("/api/v1/maker/pricing/margin/t-1", () =>
        HttpResponse.json({
          template_id: "t-1",
          target_margin_pct: "30",
          is_default: true,
        }),
      ),
    );

    renderWithQuery(
      <PricingCalculator
        open
        onClose={vi.fn()}
        templateId="t-1"
        producedQty="10"
      />,
    );

    // One value, two controls, one name: the label points at the slider,
    // the number field names itself from the same label.
    expect(
      await screen.findByRole("slider", { name: "Target margin (%)" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("spinbutton", { name: "Target margin (%)" }),
    ).toBeInTheDocument();
  });

  async function preview(compute: Record<string, unknown>) {
    server.use(
      http.get("/api/v1/maker/pricing/margin/t-1", () =>
        HttpResponse.json({
          template_id: "t-1",
          target_margin_pct: "30",
          is_default: true,
        }),
      ),
      http.post("/api/v1/maker/pricing/compute", () =>
        HttpResponse.json(compute),
      ),
    );

    renderWithQuery(
      <PricingCalculator
        open
        onClose={vi.fn()}
        templateId="t-1"
        producedQty="10"
      />,
    );

    fireEvent.click(await screen.findByTestId("maker-pricing-preview-button"));
  }

  it("refuses a sale price built on a cost nobody could compute", async () => {
    // Measured: a formula with no purchase prices priced at "TOTAL COST
    // $0.00 · UNIT COST $0.00 · SUGGESTED SALE PRICE $0.00" — the last one
    // at a 95% margin, which is a suggestion somebody would follow.
    await preview({
      template_id: "t-1",
      produced_qty: "10",
      total_cost: "0.00",
      unit_cost: "0.00",
      target_margin_pct: "30",
      unit_sale_price: "0.00",
      ingredient_count: 2,
      unrated_ingredient_count: 2,
    });

    expect(await screen.findByText("Suggested sale price")).toBeInTheDocument();
    expect(screen.queryByText(/0[.,]00/)).toBeNull();
    expect(
      screen.getAllByText(
        "No rate for any of the 2 ingredients — there is nothing to add up.",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("keeps a price computed from a partly priced formula, and says so", async () => {
    await preview({
      template_id: "t-1",
      produced_qty: "10",
      total_cost: "20.00",
      unit_cost: "2.00",
      target_margin_pct: "30",
      unit_sale_price: "2.86",
      ingredient_count: 3,
      unrated_ingredient_count: 1,
    });

    expect(await screen.findByText(/2[.,]86/)).toBeInTheDocument();
    expect(
      screen.getAllByText(
        "1 ingredient has no rate, so it is missing from this figure.",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("says a product with no formula has no formula, not an empty one", async () => {
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    await preview({
      template_id: "t-1",
      produced_qty: "10",
      total_cost: "0.00",
      unit_cost: "0.00",
      target_margin_pct: "30",
      unit_sale_price: "0.00",
      ingredient_count: 0,
      unrated_ingredient_count: 0,
      recipe_state: "no_recipe",
      recipe_id: null,
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(/no BOM/i);
    expect(screen.queryByText(/no ingredients/i)).not.toBeInTheDocument();
    expect(
      screen.getByTestId("missing-recipe-create-link"),
    ).toBeInTheDocument();
  });

  it("an empty formula keeps its sentence and gains the door to its composition", async () => {
    await preview({
      template_id: "t-1",
      produced_qty: "10",
      total_cost: "0.00",
      unit_cost: "0.00",
      target_margin_pct: "30",
      unit_sale_price: "0.00",
      ingredient_count: 0,
      unrated_ingredient_count: 0,
      recipe_state: "empty",
      recipe_id: "recipe-t1",
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /no ingredients/i,
    );
    expect(
      await screen.findByRole("link", { name: /add ingredients/i }),
    ).toHaveAttribute("href", "/maker/recipes/recipe-t1");
  });

  it("drops the previous product's result when the product changes", async () => {
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    server.use(
      http.get("/api/v1/maker/pricing/margin/:id", ({ params }) =>
        HttpResponse.json({
          template_id: params.id,
          target_margin_pct: "30",
          is_default: true,
        }),
      ),
      http.post("/api/v1/maker/pricing/compute", () =>
        HttpResponse.json({
          template_id: "t-1",
          produced_qty: "10",
          total_cost: "0.00",
          unit_cost: "0.00",
          target_margin_pct: "30",
          unit_sale_price: "0.00",
          ingredient_count: 0,
          unrated_ingredient_count: 0,
          recipe_state: "no_recipe",
          recipe_id: null,
        }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const sheet = (templateId: string) => (
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <PricingCalculator
            open
            onClose={vi.fn()}
            templateId={templateId}
            producedQty="10"
          />
        </QueryClientProvider>
      </MemoryRouter>
    );
    const { rerender } = render(sheet("t-1"));

    fireEvent.click(await screen.findByTestId("maker-pricing-preview-button"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/no BOM/i);

    rerender(sheet("t-2"));

    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});
