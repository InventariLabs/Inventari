import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { UnitCostValue } from "./UnitCostValue";

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

describe("UnitCostValue", () => {
  it("says nothing about a recipe that has never been produced", () => {
    render(<UnitCostValue value={null} uncosted={0} />);

    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows the amount when every ingredient of the run was priced", () => {
    render(<UnitCostValue value="5.00" uncosted={0} />);

    expect(screen.getByText(/5[.,]00/)).toBeInTheDocument();
    expect(screen.queryByText(/purchase cost/)).toBeNull();
  });

  it("refuses to state a zero built entirely from unknowns", () => {
    // Measured on the catalog: ingredients with no purchase price are costed
    // at zero so the run can complete, and the card printed "Unit cost $0.00"
    // — the one reading that says the product is free to make, which is what
    // somebody then sets a margin against.
    render(<UnitCostValue value="0.0000" uncosted={4} />);

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(
      screen.getByText(
        "4 ingredients in the last run had no purchase cost recorded.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps a partial number but marks how much of the recipe it misses", () => {
    // Two of five priced is worth something; passing it off as the cost is
    // not. The number stays, the omission is stated.
    render(<UnitCostValue value="3.20" uncosted={1} />);

    expect(screen.getByText(/3[.,]20/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "1 ingredient in the last run had no purchase cost recorded.",
      ),
    ).toBeInTheDocument();
  });

  it("does not tell a zero cost apart from an unknown one when the run was fully priced", () => {
    // A recipe whose ingredients are all genuinely free costs zero, and that
    // is a measurement — it keeps its number.
    render(<UnitCostValue value="0.00" uncosted={0} />);

    expect(screen.getByText(/0[.,]00/)).toBeInTheDocument();
    expect(screen.queryByText("—")).toBeNull();
  });
});
