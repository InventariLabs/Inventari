import { describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InlinePopover } from "./InlinePopover";

describe("InlinePopover", () => {
  it("renders the panel through a portal on the popover layer, escaping clipping ancestors", () => {
    const { container } = render(
      <div className="overflow-hidden">
        <InlinePopover
          open
          onOpenChange={vi.fn()}
          trigger={<button type="button">Open</button>}
        >
          <div>Panel content</div>
        </InlinePopover>
      </div>,
    );
    const clipped = container.firstElementChild!;
    const panel = screen.getByText("Panel content");
    // The hand-rolled predecessor rendered `absolute … z-50` inside the row,
    // where an overflow-hidden ancestor cut it off (the class of
    // defect). The portal puts the panel outside those ancestors.
    expect(clipped).not.toContainElement(panel);
    expect(panel.parentElement?.className).toContain("z-[var(--z-popover)]");
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(true);
      return (
        <InlinePopover
          open={open}
          onOpenChange={setOpen}
          trigger={<button type="button">Open</button>}
        >
          <div>Panel content</div>
        </InlinePopover>
      );
    }
    render(<Harness />);
    expect(screen.getByText("Panel content")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByText("Panel content")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open" })).toHaveFocus();
  });
});
