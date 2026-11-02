/**
 * regression: the bulk bar offers "Return Selected" and the batch
 * return dialog asks for ONE checkin condition for the whole batch.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/test/utils";
import { AssetBulkActionsBar } from "@/modules/equipment/components/AssetBulkActionsBar";
import { BulkReturnModal } from "@/modules/equipment/components/BulkReturnModal";

describe(" bulk return", () => {
  it("offers Return Selected in the active bulk bar", () => {
    render(
      <AssetBulkActionsBar
        selectedCount={5}
        unreachedMatches={0}
        matchingTotal={5}
        allMatching={false}
        onSelectAllMatching={vi.fn()}
        listTab="active"
        onBulkRetire={vi.fn()}
        onBulkReturn={vi.fn()}
        onBulkArchive={vi.fn()}
        onBulkPrintLabels={vi.fn()}
        onBulkPurge={vi.fn()}
        onBulkChangeStatus={vi.fn()}
        onBulkChangeLocation={vi.fn()}
        onBulkAssignTo={vi.fn()}
        onClearSelection={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Return Selected" }),
    ).toBeInTheDocument();
  });

  it("submits one condition for the whole batch", () => {
    const onConfirm = vi.fn();
    render(
      <BulkReturnModal
        selectedCount={5}
        returnableCount={5}
        isPending={false}
        onConfirm={onConfirm}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("radio", { name: /^Damaged/ }));
    fireEvent.click(screen.getByRole("button", { name: "Return" }));

    // Each asset goes back to its own location unless one place is chosen.
    expect(onConfirm).toHaveBeenCalledWith({
      condition: "DAMAGED",
      notes: undefined,
      returnLocationId: undefined,
    });
  });

  it("offers one place for the whole batch, each to its own by default", () => {
    render(
      <BulkReturnModal
        selectedCount={2}
        returnableCount={2}
        isPending={false}
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Returns to")).toBeInTheDocument();
    expect(
      screen.getAllByText("Each to its own location").length,
    ).toBeGreaterThan(0);
  });

  it("counts what it will return, not what is selected", () => {
    render(
      <BulkReturnModal
        selectedCount={5}
        returnableCount={2}
        isPending={false}
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    // The title is also mirrored into the dialog's screen-reader description.
    expect(
      screen.getAllByText("Return 2 selected assets?").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByText(
        "3 of the 5 selected assets are on a shelf; the return covers the rest.",
      ),
    ).toBeInTheDocument();
  });

  it("says the condition covers the whole batch", () => {
    render(
      <BulkReturnModal
        selectedCount={2}
        returnableCount={2}
        isPending={false}
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/The condition applies to every asset returned here/),
    ).toBeInTheDocument();
  });
});
