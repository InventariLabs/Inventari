import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AssetStatusMenu } from "./AssetStatusMenu";
import { render } from "@/test/utils";

/**
 * "Checked Out" is the reader-facing name of DEPLOYED (equipment i18n). The
 * menu lists the current status even when it cannot set it, so the reader
 * always sees where they stand.
 */
describe("AssetStatusMenu", () => {
  it("does not offer maintenance on a checked-out asset, and says why", async () => {
    // Offering MAINTENANCE on an asset someone holds produced two
    // screens saying "maintenance" while the overview deliberately kept
    // counting the row as deployed. The way in is checkin, not this menu —
    // and the absent row explains itself, the way retire already does.
    const user = userEvent.setup();
    render(
      <AssetStatusMenu currentStatus="DEPLOYED" onChangeStatus={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: "Change status" }));
    const menu = screen.getByRole("menu");
    expect(menu).toHaveTextContent("Checked Out");
    expect(menu).toHaveTextContent("Available");
    expect(menu).toHaveTextContent(
      "Cannot set Maintenance — return the asset first",
    );
    expect(
      screen.queryByRole("menuitemradio", { name: "Maintenance" }),
    ).not.toBeInTheDocument();
  });

  it("still offers maintenance while the asset is in stock", async () => {
    const user = userEvent.setup();
    render(
      <AssetStatusMenu currentStatus="AVAILABLE" onChangeStatus={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: "Change status" }));
    expect(screen.getByRole("menu")).toHaveTextContent("Maintenance");
  });
});
