/**
 * regression: "retire" and "archive" are two distinct operations.
 *
 * - Retire sets the RETIRED status and keeps the asset in the register.
 * - Archive is the soft delete that moves the asset to the archived tab.
 * The bulk bar offers both, and the confirm dialogs say what they do.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { AssetBulkActionsBar } from "@/modules/equipment/components/AssetBulkActionsBar";
import { AssetConfirmDialogs } from "@/modules/equipment/components/AssetConfirmDialogs";

describe(" retire vs archive", () => {
  it("offers both Retire Selected and Archive in the active bulk bar", () => {
    render(
      <AssetBulkActionsBar
        selectedCount={2}
        unreachedMatches={0}
        matchingTotal={5}
        allMatching={false}
        onSelectAllMatching={vi.fn()}
        listTab="active"
        onBulkRetire={vi.fn()}
        onBulkArchive={vi.fn()}
        onBulkPrintLabels={vi.fn()}
        onBulkReturn={vi.fn()}
        onBulkPurge={vi.fn()}
        onBulkChangeStatus={vi.fn()}
        onBulkChangeLocation={vi.fn()}
        onBulkAssignTo={vi.fn()}
        onClearSelection={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Retire Selected" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Archive Selected" }),
    ).toBeInTheDocument();
  });

  it("retire confirmation keeps the asset in the register", () => {
    render(
      <AssetConfirmDialogs
        selectedCount={2}
        showBulkRetireConfirm
        showBulkArchiveConfirm={false}
        showBulkPurgeConfirm={false}
        restoreTarget={null}
        purgeTarget={null}
        onBulkRetire={vi.fn()}
        onBulkArchive={vi.fn()}
        onBulkPurge={vi.fn()}
        onRestore={vi.fn()}
        onSinglePurge={vi.fn()}
        onCancelBulkRetire={vi.fn()}
        onCancelBulkArchive={vi.fn()}
        onCancelBulkPurge={vi.fn()}
        onCancelRestore={vi.fn()}
        onCancelPurge={vi.fn()}
      />,
    );

    expect(screen.getByText(/remain in the register/)).toBeInTheDocument();
    // A checked-out asset is refused only after the press ("return the asset
    // first"); the question says so before it is answered.
    expect(
      screen.getByText(/A checked-out asset is not retired — return it first/),
    ).toBeInTheDocument();
  });

  it("archive confirmation moves the asset to the archive", () => {
    render(
      <AssetConfirmDialogs
        selectedCount={2}
        showBulkRetireConfirm={false}
        showBulkArchiveConfirm
        showBulkPurgeConfirm={false}
        restoreTarget={null}
        purgeTarget={null}
        onBulkRetire={vi.fn()}
        onBulkArchive={vi.fn()}
        onBulkPurge={vi.fn()}
        onRestore={vi.fn()}
        onSinglePurge={vi.fn()}
        onCancelBulkRetire={vi.fn()}
        onCancelBulkArchive={vi.fn()}
        onCancelBulkPurge={vi.fn()}
        onCancelRestore={vi.fn()}
        onCancelPurge={vi.fn()}
      />,
    );

    expect(screen.getByText(/moved to the archive/)).toBeInTheDocument();
  });
});
