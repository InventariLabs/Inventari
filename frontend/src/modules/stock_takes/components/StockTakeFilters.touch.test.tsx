import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils";
import StockTakeFilters from "./StockTakeFilters";

/**
 * The counting screen's two filter chips measured 38px tall on a 390px
 * screen — under the 44px touch floor the rest of the app holds below `md`.
 * The floor is a height a class declares, so this asserts the class; jsdom
 * lays nothing out.
 */
describe("StockTakeFilters — touch targets", () => {
  it("gives both chips the floor", () => {
    render(
      <StockTakeFilters
        showDiscrepancies={false}
        onShowAll={vi.fn()}
        onShowDiscrepancies={vi.fn()}
        totalCount={8}
        discrepanciesCount={3}
        surplusCount={0}
        locationLevels={[]}
        locationLevelFilter=""
        onLocationLevelFilterChange={vi.fn()}
      />,
    );

    for (const label of ["All (8)", "Discrepancies (3)"]) {
      const chip = screen.getByRole("button", { name: label });
      expect(String(chip.className)).toContain("min-h-11");
      expect(String(chip.className)).toContain("md:min-h-8");
    }
  });
});
