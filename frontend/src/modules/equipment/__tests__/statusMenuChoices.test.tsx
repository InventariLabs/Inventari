import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/test/utils";
import { AssetStatusMenu } from "@/modules/equipment/components/AssetStatusMenu";

/**
 * The menu offered all four statuses, so an asset could be marked deployed
 * with nobody holding it, and retired in one click — the same operation the
 * bulk bar guards with a confirmation dialog.
 */
describe("what the status menu may set", () => {
  function open(currentStatus: "AVAILABLE" | "DEPLOYED" | "MAINTENANCE") {
    render(
      <AssetStatusMenu
        currentStatus={currentStatus}
        onChangeStatus={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Change status" }));
  }

  it("offers the states that describe condition, not consequence", () => {
    open("AVAILABLE");

    const choices = screen
      .getAllByRole("menuitemradio")
      .map((item) => item.textContent?.trim());
    expect(choices).toEqual(["Available", "Maintenance"]);
  });

  it("leaves deploying to a checkout and retiring to its own action", () => {
    open("AVAILABLE");

    expect(
      screen.queryByRole("menuitemradio", { name: "Checked Out" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("menuitemradio", { name: "Retired" }),
    ).not.toBeInTheDocument();
  });

  it("still shows where the asset currently stands", () => {
    open("DEPLOYED");

    const current = screen.getByRole("menuitemradio", { name: "Checked Out" });
    expect(current).toHaveAttribute("aria-checked", "true");
    expect(current).toBeDisabled();
  });
});
