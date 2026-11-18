import { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/Dialog";

function Controlled({ unmountOpener = false }: { unmountOpener?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      {!(unmountOpener && open) && (
        <button type="button" onClick={() => setOpen(true)}>
          Edit rule
        </button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle>Rule</DialogTitle>
          <DialogDescription>Edit the rule</DialogDescription>
          <button type="button" onClick={() => setOpen(false)}>
            Cancel
          </button>
        </DialogContent>
      </Dialog>
    </>
  );
}

describe("Dialog", () => {
  it("returns focus to the button that opened it when Escape closes it", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    const opener = screen.getByRole("button", { name: "Edit rule" });
    opener.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(opener).toHaveFocus();
  });

  it("returns focus to the opener when Cancel closes it", async () => {
    render(<Controlled />);
    const opener = screen.getByRole("button", { name: "Edit rule" });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(opener).toHaveFocus();
  });

  it("leaves focus alone when the opener is gone", async () => {
    const user = userEvent.setup();
    render(<Controlled unmountOpener />);
    const opener = screen.getByRole("button", { name: "Edit rule" });
    opener.focus();
    await user.keyboard("{Enter}");
    await screen.findByRole("dialog");

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.body).toHaveFocus();
  });
});
