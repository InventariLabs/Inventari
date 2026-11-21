import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "@/test/utils";
import { FleetCompositionCard } from "./FleetCompositionCard";

/**
 * Retired assets are deliberately out of the fleet (bucketFleet drops them),
 * so a register holding only retired assets draws an empty card. The empty
 * copy does not say "No assets in the register yet" — the register the retire
 * dialog promised the asset would remain in — while the asset list still
 * shows it. The card is about the fleet, and says so.
 */
describe("FleetCompositionCard — an empty fleet is not an empty register", () => {
  it("names the fleet, not the register, when nothing counts in it", () => {
    render(
      <FleetCompositionCard
        rows={[]}
        isLoading={false}
        error={null}
        onRetry={vi.fn()}
      />,
    );

    expect(
      screen.getByText("The fleet has no assets yet."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/register/i)).not.toBeInTheDocument();
  });

  it("says the assets are retired when some are and none counts in the fleet", () => {
    render(
      <FleetCompositionCard
        rows={[]}
        isLoading={false}
        error={null}
        onRetry={vi.fn()}
        retiredCount={1}
      />,
    );

    expect(
      screen.getByText(
        "Every asset on record is retired, so none is in the fleet.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no assets yet/i)).not.toBeInTheDocument();
  });
});
