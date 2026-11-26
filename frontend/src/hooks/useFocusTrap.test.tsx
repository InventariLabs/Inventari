import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { useFocusTrap } from "./useFocusTrap";

function TrapContainer({ isActive }: { isActive: boolean }) {
  const ref = useFocusTrap(isActive);
  return (
    <div ref={ref as React.RefObject<HTMLDivElement>}>
      <button>First</button>
      <button>Second</button>
      <button>Third</button>
    </div>
  );
}

describe("useFocusTrap", () => {
  it("returns a ref object", () => {
    let capturedRef: ReturnType<typeof useFocusTrap> | undefined;
    function Test() {
      capturedRef = useFocusTrap(false);
      return null;
    }
    render(<Test />);
    expect(capturedRef).toBeDefined();
    expect(capturedRef).toHaveProperty("current");
  });

  it("focuses first focusable element when activated", () => {
    render(<TrapContainer isActive={true} />);
    // After activation, first button should receive focus
    expect(document.activeElement?.textContent).toBe("First");
  });

  it("leaves the focus on a control inside that took it as it mounted", () => {
    function TrapWithField() {
      const ref = useFocusTrap(true);
      return (
        <div ref={ref as React.RefObject<HTMLDivElement>}>
          <button>Close</button>
          <input aria-label="Code" autoFocus />
        </div>
      );
    }
    render(<TrapWithField />);

    expect(screen.getByRole("textbox", { name: "Code" })).toHaveFocus();
  });

  it("does not auto-focus when inactive", () => {
    const previousFocus = document.body;
    render(<TrapContainer isActive={false} />);
    expect(document.activeElement).toBe(previousFocus);
  });

  it("wraps Tab key from last to first element", () => {
    render(<TrapContainer isActive={true} />);
    const buttons = screen.getAllByRole("button");
    const lastButton = buttons[buttons.length - 1];

    lastButton.focus();
    expect(document.activeElement).toBe(lastButton);

    fireEvent.keyDown(document, { key: "Tab", shiftKey: false });
    expect(document.activeElement?.textContent).toBe("First");
  });

  it("wraps Shift+Tab key from first to last element", () => {
    render(<TrapContainer isActive={true} />);
    const buttons = screen.getAllByRole("button");
    const firstButton = buttons[0];

    firstButton.focus();
    expect(document.activeElement).toBe(firstButton);

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement?.textContent).toBe("Third");
  });

  it("hands the focus back to the opener when a field took it as the sheet mounted", () => {
    function Page() {
      const [open, setOpen] = React.useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Open</button>
          {open && <Sheetlike onClose={() => setOpen(false)} />}
        </>
      );
    }
    function Sheetlike({ onClose }: { onClose: () => void }) {
      const ref = useFocusTrap(true);
      return (
        <div ref={ref as React.RefObject<HTMLDivElement>}>
          <button onClick={onClose}>Close</button>
          <input aria-label="Code" autoFocus />
        </div>
      );
    }
    render(<Page />);
    const opener = screen.getByRole("button", { name: "Open" });
    opener.focus();
    fireEvent.click(opener);
    expect(screen.getByRole("textbox", { name: "Code" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(opener).toHaveFocus();
  });
});
