import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { AvailabilityBadge } from "./AvailabilityBadge";
import { withLanguage } from "@/test/mocks/i18n";
import type { AvailabilityResponse } from "@/modules/maker/types/maker";

const mocks = vi.hoisted(() => ({
  useMakerRecipeAvailability: vi.fn(),
}));

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerRecipeAvailability: mocks.useMakerRecipeAvailability,
}));

function availability(
  overrides: Partial<AvailabilityResponse> = {},
): AvailabilityResponse {
  return {
    max_batches: "4.0000",
    has_shortage: false,
    has_unknown: false,
    ingredients: [
      {
        child_template_id: "tpl-flour",
        child_template_name: "Flour",
        needed: "5.000000",
        available: "20.000000",
        shortage: "0",
        uom_symbol: "kg",
        convertible: true,
      },
    ],
    ...overrides,
  };
}

describe("AvailabilityBadge", () => {
  beforeEach(() => {
    mocks.useMakerRecipeAvailability.mockReset();
  });

  it("requests availability for one batch by default", () => {
    mocks.useMakerRecipeAvailability.mockReturnValue({
      data: availability(),
      isLoading: false,
    });
    render(<AvailabilityBadge recipeId="recipe-1" />);
    expect(mocks.useMakerRecipeAvailability).toHaveBeenCalledWith(
      "recipe-1",
      "1",
    );
  });

  it("writes coverage as the ratio the recipe cards write", () => {
    mocks.useMakerRecipeAvailability.mockReturnValue({
      data: availability(),
      isLoading: false,
    });
    render(<AvailabilityBadge recipeId="recipe-1" />);
    const badge = screen.getByTestId("availability-badge-ok");
    expect(badge).toHaveTextContent("1/1 in stock");
    expect(badge).toHaveTextContent("1 of 1 in stock");
    expect(badge).toHaveTextContent("Max batches from stock: 4");
  });

  it("shows shortage state when an ingredient is short", () => {
    mocks.useMakerRecipeAvailability.mockReturnValue({
      data: availability({
        has_shortage: true,
        max_batches: "0.0000",
        ingredients: [
          {
            child_template_id: "tpl-flour",
            child_template_name: "Flour",
            needed: "5.000000",
            available: "0",
            shortage: "5.000000",
            uom_symbol: "kg",
            convertible: true,
          },
        ],
      }),
      isLoading: false,
    });
    render(<AvailabilityBadge recipeId="recipe-1" />);
    const badge = screen.getByTestId("availability-badge-short");
    expect(badge).toHaveTextContent("0/1 in stock");
    expect(badge).toHaveTextContent("Max batches from stock: 0");
  });

  it("says the availability is unknown when a measure has no bridge", () => {
    mocks.useMakerRecipeAvailability.mockReturnValue({
      data: availability({
        max_batches: null,
        has_unknown: true,
        ingredients: [
          {
            child_template_id: "tpl-oil",
            child_template_name: "Oil",
            needed: "5.000000",
            available: "100.000000",
            shortage: null,
            uom_symbol: "kg",
            convertible: false,
            available_uom_symbol: "l",
          },
        ],
      }),
      isLoading: false,
    });
    render(<AvailabilityBadge recipeId="recipe-1" />);
    const badge = screen.getByTestId("availability-badge-unknown");
    expect(badge).toHaveTextContent("1 ingredient cannot be compared");
    // No ratio here: an ingredient nobody could measure is not an ingredient
    // known to be missing, and "0/1 in stock" would count what nobody counted.
    expect(badge).not.toHaveTextContent("in stock");
    // No batch count exists, so none is claimed.
    expect(badge).not.toHaveTextContent("Max batches from stock");
    expect(screen.queryByTestId("availability-badge-ok")).toBeNull();
  });

  it("renders nothing for a recipe without ingredients", () => {
    mocks.useMakerRecipeAvailability.mockReturnValue({
      data: availability({ ingredients: [], max_batches: "0" }),
      isLoading: false,
    });
    const { container } = render(<AvailabilityBadge recipeId="recipe-1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while loading", () => {
    mocks.useMakerRecipeAvailability.mockReturnValue({
      data: undefined,
      isLoading: true,
    });
    const { container } = render(<AvailabilityBadge recipeId="recipe-1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("counts batches the way every screen writes numbers, thousands grouped", async () => {
    // max_batches went through its own locale formatter while the rest of
    // the module did not group — "12 345,5" here and "12345,5" beside it.
    // Quantities now group everywhere, so the badge agrees with its page.
    mocks.useMakerRecipeAvailability.mockReturnValue({
      data: availability({ max_batches: "12345.5000" }),
      isLoading: false,
    });
    await withLanguage("pl", () => {
      render(<AvailabilityBadge recipeId="recipe-1" />);
      const badge = screen.getByTestId("availability-badge-ok");
      expect(badge).toHaveTextContent("Maks. partii ze stanu: 12 345,5");
    });
  });
});
