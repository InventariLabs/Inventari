import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { AssetDetailHeaderActions } from "@/modules/equipment/components/AssetDetailHeaderActions";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const noop = vi.fn();

function renderActions(overrides: Record<string, unknown> = {}) {
  render(
    <MemoryRouter>
      <AssetDetailHeaderActions
        itemId="item-1"
        status="AVAILABLE"
        isArchived={false}
        activeAssignment={null}
        approvalStatus={undefined}
        onRequestApproval={noop}
        onChangeStatus={noop}
        bulkEditPending={false}
        onCheckout={noop}
        onCheckin={noop}
        onRestore={noop}
        onPurge={noop}
        onRetire={noop}
        onArchive={noop}
        {...overrides}
      />
    </MemoryRouter>,
  );
}

/**
 * The edit link was a ghost icon button with neither a label nor a tooltip:
 * a screen reader announced "button" and stopped, beside a control that
 * takes the asset off the active list.
 */
describe("icon controls on the asset detail header", () => {
  it("names every one of them", () => {
    renderActions();

    expect(
      screen.getByRole("button", { name: "Edit asset" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retire" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
  });

  it("says why retiring is unavailable, on the screen and in the name", () => {
    renderActions({
      status: "DEPLOYED",
      activeAssignment: {
        id: "a-1",
        item_id: "item-1",
        assigned_to_name: "Anna Kowalska",
        checked_in_at: null,
      },
    });

    const blocked = screen.getByRole("button", {
      name: "Cannot retire — return the asset first",
    });
    expect(blocked).toBeDisabled();
    // The reason used to live in `title` alone, which a finger never sees.
    expect(
      screen.getByText("Cannot retire — return the asset first"),
    ).toBeInTheDocument();
  });
});
