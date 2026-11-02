import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Dialog, DialogContent, DialogTitle } from "../Dialog";
import { Sheet, SheetBody } from "../Sheet";

/**
 * A sheet opened from inside a dialog takes the Escape for itself.
 *
 * Measured in a browser at 390px: opening the campaign dialog, typing a name,
 * opening the deadline picker — a sheet at that width — and pressing Escape
 * closed the picker *and* the dialog, so the half-filled form was gone in one
 * keystroke. Radix listens for Escape on `document` in the capture phase and
 * registered first, so the sheet's own listener never got the chance to keep
 * the dialog open.
 */

function DialogWithSheet() {
  const [sheetOpen, setSheetOpen] = useState(true);
  // Uncontrolled-in-practice: the dialog really closes when Radix says so,
  // which is the whole point of the assertion below.
  const [dialogOpen, setDialogOpen] = useState(true);

  return (
    <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
      <DialogContent aria-describedby={undefined}>
        <DialogTitle>Campaign</DialogTitle>
        <input aria-label="name" defaultValue="Q1 audit" />
        {sheetOpen && (
          <Sheet open onClose={() => setSheetOpen(false)} aria-label="date">
            <SheetBody>calendar</SheetBody>
          </Sheet>
        )}
      </DialogContent>
    </Dialog>
  );
}

describe("a sheet opened inside a dialog", () => {
  it("closes on Escape and leaves the dialog behind it open", () => {
    render(<DialogWithSheet />);

    expect(screen.getByRole("dialog", { name: "date" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(
      screen.queryByRole("dialog", { name: "date" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("name")).toHaveValue("Q1 audit");
  });

  it("stops holding the Escape once it is gone", () => {
    function PlainDialog() {
      const [open, setOpen] = useState(true);
      return (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent aria-describedby={undefined}>
            <DialogTitle>Campaign</DialogTitle>
          </DialogContent>
        </Dialog>
      );
    }
    render(<PlainDialog />);

    // No sheet on top: the dialog is free to take the key itself, which is
    // what the counter has to give back when the last sheet unmounts.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("Campaign")).not.toBeInTheDocument();
  });
});
