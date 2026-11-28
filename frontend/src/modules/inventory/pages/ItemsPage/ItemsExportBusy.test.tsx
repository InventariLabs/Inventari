import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { onePreparedAtATime } from "@/modules/shared/lib/exportProgress";
import { ItemsHeaderActions } from "./ItemsHeaderActions";
import { ItemsMobileActionsSheet } from "./ItemsMobileActionsSheet";

const list = { canWrite: false, hasRows: true, listFailed: false };

/** Both doors to the product export show that its file is on the way. */
describe.each([
  [
    "the header",
    () => (
      <ItemsHeaderActions
        {...list}
        selectionMode={false}
        onExitSelectionMode={vi.fn()}
        onOpenMobileActions={vi.fn()}
        onImport={vi.fn()}
        onExport={vi.fn()}
        onAddProduct={vi.fn()}
      />
    ),
  ],
  [
    "the phone's sheet",
    () => (
      <ItemsMobileActionsSheet
        {...list}
        open
        onClose={vi.fn()}
        onImport={vi.fn()}
        onExport={vi.fn()}
        onOpenCategories={vi.fn()}
        onSelectItems={vi.fn()}
      />
    ),
  ],
])("the Export button in %s", (_where, door) => {
  it("is disabled, with a spinner, while the export is being prepared", async () => {
    let finish!: () => void;
    render(door());
    const button = screen.getByRole("button", { name: "Export" });
    let running!: Promise<void>;

    act(() => {
      running = onePreparedAtATime(
        "items-export",
        () =>
          new Promise<void>((resolve) => {
            finish = resolve;
          }),
      );
    });

    expect(button).toBeDisabled();
    expect(button.querySelector(".animate-spin")).not.toBeNull();
    await act(async () => {
      finish();
      await running;
    });
    expect(button).toBeEnabled();
  });
});
