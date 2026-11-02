import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ModalShell } from "./ModalShell";

/**
 * The backdrop must only close on a press that *started* on it. A press that
 * starts on a child and ends on the backdrop (because the content shrank under
 * the cursor) reaches the backdrop as a `click` — see.
 */
describe("ModalShell backdrop guard", () => {
  const setup = (onClose: () => void) => {
    render(
      <ModalShell open onClose={onClose}>
        <button>Inside</button>
      </ModalShell>,
    );
    const inside = screen.getByRole("button", { name: "Inside" });
    // `contents` wrapper -> backdrop
    const backdrop = inside.parentElement!.parentElement as HTMLElement;
    return { inside, backdrop };
  };

  it("closes when the whole press happens on the backdrop", () => {
    const onClose = vi.fn();
    const { backdrop } = setup(onClose);
    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close when the press starts on content and lands on the backdrop", () => {
    const onClose = vi.fn();
    const { inside, backdrop } = setup(onClose);
    fireEvent.mouseDown(inside);
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not close on a click with no preceding press on the backdrop", () => {
    const onClose = vi.fn();
    const { backdrop } = setup(onClose);
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not close when clicking inside the content", () => {
    const onClose = vi.fn();
    const { inside } = setup(onClose);
    fireEvent.mouseDown(inside);
    fireEvent.click(inside);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("renders nothing when closed", () => {
    render(
      <ModalShell open={false} onClose={() => {}}>
        <div>content</div>
      </ModalShell>,
    );
    expect(screen.queryByText("content")).toBeNull();
  });
});

/**
 * Rendered in place, the overlay is a flow sibling of the page around it. A
 * container with `space-y-*` gives every such sibling a top margin, which
 * pushed the overlay down 24px and left the top of the app bar undimmed and
 * clickable. jsdom has no stylesheet, so this pins the class that cancels it.
 */
describe("ModalShell inside a spaced container", () => {
  it("cancels the margin a space-y parent would hand its overlay", () => {
    render(
      <div className="space-y-6">
        <p>Page</p>
        <ModalShell open>
          <button>Inside</button>
        </ModalShell>
      </div>,
    );
    const overlay = screen.getByRole("button", { name: "Inside" })
      .parentElement!.parentElement as HTMLElement;
    expect(overlay.className).toContain("fixed");
    expect(overlay.className).toContain("!m-0");
  });
});
