import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import AlwaysAtHomePage from "./AlwaysAtHomePage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

vi.mock("@/modules/recipes/hooks/useMealPlans", () => ({
  useShoppingExclusions: () => ({ data: [], isLoading: false }),
  useCreateShoppingExclusion: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteShoppingExclusion: () => ({ mutate: vi.fn() }),
}));

describe("AlwaysAtHomePage — the empty list explains itself", () => {
  it("splits the how-to sentence out of the empty-state title", () => {
    render(<AlwaysAtHomePage />);

    const empty = screen.getByTestId("empty-state");
    expect(within(empty).getByText("No exclusions yet")).toBeInTheDocument();
    expect(
      within(empty).getByText(
        "Mark ingredients from a recipe or type a name above — they will be left off every shopping list.",
      ),
    ).toBeInTheDocument();
  });
});
