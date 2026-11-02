import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "@/test/utils";
import { FleetCompositionCard } from "./FleetCompositionCard";

/**
 * Retired assets are deliberately out of the fleet (bucketFleet drops them),
 * so a register holding only retired assets draws an empty card. The empty
 * copy used to say "No assets in the register yet" — the register the retire
 * dialog promised the asset would remain in — while the asset list still
 * showed it. The card is about the fleet, and now says so.
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
});
