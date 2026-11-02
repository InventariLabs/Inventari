import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "./Sheet";

describe("Sheet", () => {
  it("renders nothing when closed", () => {
    render(
      <Sheet open={false} onClose={() => {}}>
        <div>content</div>
      </Sheet>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders content with role=dialog when open", () => {
    render(
      <Sheet open={true} onClose={() => {}}>
        <div>content</div>
      </Sheet>,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("content")).toBeInTheDocument();
  });

  it("marks the dialog as modal", () => {
    render(
      <Sheet open={true} onClose={() => {}}>
        <div>content</div>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("sets aria-label when provided", () => {
    render(
      <Sheet open={true} onClose={() => {}} aria-label="Edit item">
        <div>content</div>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-label", "Edit item");
  });

  it("sets aria-describedby when provided", () => {
    render(
      <Sheet open={true} onClose={() => {}} aria-describedby="my-desc">
        <div>content</div>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-describedby", "my-desc");
  });

  it("calls onClose on Escape key", () => {
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose}>
        <div>content</div>
      </Sheet>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("leaves Escape to a list opened inside it", () => {
    // A unit list, an ingredient suggestion, a date picker: Radix closes its
    // own layer from a document listener, and the sheet used to close itself
    // in the same keystroke — so Escape aimed at the list threw away the form
    // underneath it.
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose}>
        <div>content</div>
      </Sheet>,
    );
    const popper = document.createElement("div");
    popper.setAttribute("data-radix-popper-content-wrapper", "");
    document.body.appendChild(popper);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    popper.remove();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("leaves Escape to a suggestion list that holds results", () => {
    // The product picker of a line editor is not a Radix layer; its input
    // closes it from a key handler that runs after this sheet's listener, so
    // Escape aimed at the list used to close the sheet around it.
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose}>
        <div>content</div>
      </Sheet>,
    );
    const list = document.createElement("div");
    list.setAttribute("role", "listbox");
    document.body.appendChild(list);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    list.remove();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("leaves Escape to an empty suggestion list too", () => {
    // The product picker's panel is a listbox only while it holds results;
    // with nothing found it showed the picker marker alone, and the sheet
    // closed — or asked its discard question — on a press aimed at the
    // panel.
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose}>
        <div>content</div>
      </Sheet>,
    );
    const panel = document.createElement("div");
    panel.setAttribute("data-line-item-dropdown", "");
    document.body.appendChild(panel);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    panel.remove();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("leaves Escape to a question raised over it", () => {
    // A discard guard — `ConfirmDialog` is Radix's alertdialog. Radix
    // dismisses it from its own listener; a sheet that also acted on the press
    // would close, or ask its question a second time, in the keystroke meant
    // to answer it.
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose}>
        <div>content</div>
      </Sheet>,
    );
    const question = document.createElement("div");
    question.setAttribute("role", "alertdialog");
    document.body.appendChild(question);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    question.remove();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("answers before a listener mounted by the same press can read it", () => {
    // The discard question is a layer mounting inside the flush this handler
    // triggers; Radix registers its own Escape listener there, while the key
    // event is still travelling, and stands down on a press that comes back
    // prevented. Hence the capture phase: a listener registered later in it
    // must already see `defaultPrevented`.
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose}>
        <div>content</div>
      </Sheet>,
    );
    const seen = vi.fn();
    const late = (e: KeyboardEvent) => seen(e.defaultPrevented);
    document.addEventListener("keydown", late, true);

    fireEvent.keyDown(document, { key: "Escape" });

    document.removeEventListener("keydown", late, true);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(seen).toHaveBeenCalledWith(true);
  });

  it("calls onClose on backdrop click", () => {
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose}>
        <div>content</div>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog");
    // Click on the backdrop (parent of dialog)
    const backdrop = dialog.parentElement as HTMLElement;
    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close on backdrop click when closeOnBackdropClick is false", () => {
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose} closeOnBackdropClick={false}>
        <div>content</div>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog");
    const backdrop = dialog.parentElement as HTMLElement;
    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not close when clicking inside the dialog", () => {
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose}>
        <button>Inside button</button>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("locks body scroll when open", () => {
    const original = document.body.style.overflow;
    render(
      <Sheet open={true} onClose={() => {}}>
        <div>content</div>
      </Sheet>,
    );
    expect(document.body.style.overflow).toBe("hidden");
    document.body.style.overflow = original;
  });

  it("applies custom z-index tier", () => {
    render(
      <Sheet open={true} onClose={() => {}} zIndex="confirm">
        <div>content</div>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog");
    const backdrop = dialog.parentElement as HTMLElement;
    expect(backdrop.style.zIndex).toBe("var(--z-confirm)");
  });

  it("full-bleed: panel fills the height and only rounds from sm up", () => {
    render(
      <Sheet open={true} onClose={() => {}} fullBleedOnMobile maxWidth="xl">
        <div>content</div>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("h-full");
    expect(dialog.className).toContain("sm:rounded-2xl");
    expect(dialog.className).toContain("sm:max-w-xl");
    // no mobile rounding / mobile max-width in this mode
    expect(dialog.className).not.toContain("rounded-t-3xl");
    expect(dialog.className).not.toContain(" max-w-xl");
  });

  it("full-bleed: backdrop is the surface on mobile, dimmed from sm up", () => {
    render(
      <Sheet open={true} onClose={() => {}} fullBleedOnMobile>
        <div>content</div>
      </Sheet>,
    );
    const backdrop = screen.getByRole("dialog").parentElement!;
    expect(backdrop.className).toContain("bg-surface-card");
    expect(backdrop.className).toContain("sm:bg-black/50");
  });

  it("full-bleed: backdrop click does not close", () => {
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose} fullBleedOnMobile>
        <div>content</div>
      </Sheet>,
    );
    const backdrop = screen.getByRole("dialog").parentElement!;
    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("backdrop click still closes a normal sheet", () => {
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose}>
        <div>content</div>
      </Sheet>,
    );
    const backdrop = screen.getByRole("dialog").parentElement!;
    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("full bleed: the panel is the screen at every width", () => {
    // The fullscreen layer's own surface — a wizard standing in front of the
    // application rather than a card over it (UI_GUIDELINES §4.1).
    render(
      <Sheet open={true} onClose={() => {}} fullBleed maxWidth="lg">
        <div>content</div>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog");
    const backdrop = dialog.parentElement!;
    expect(dialog.className).toContain("h-full");
    // No width of its own to cap, and nothing to round or centre.
    expect(dialog.className).not.toContain("max-w-lg");
    expect(dialog.className).not.toContain("rounded");
    expect(backdrop.className).toContain("bg-surface-card");
    expect(backdrop.className).not.toContain("sm:items-center");
    expect(backdrop.className).not.toContain("bg-black/50");
  });

  it("full bleed: there is no backdrop, so there is no backdrop click", () => {
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose} fullBleed>
        <div>content</div>
      </Sheet>,
    );
    const backdrop = screen.getByRole("dialog").parentElement!;
    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("full bleed: Escape still closes it", () => {
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose} fullBleed>
        <div>content</div>
      </Sheet>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("applies maxWidth class", () => {
    render(
      <Sheet open={true} onClose={() => {}} maxWidth="3xl">
        <div>content</div>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("max-w-3xl");
  });

  it("does not close when the press starts inside and lands on the backdrop", () => {
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose}>
        <button>Inside button</button>
      </Sheet>,
    );
    const backdrop = screen.getByRole("dialog").parentElement!;
    fireEvent.mouseDown(screen.getByRole("button", { name: "Inside button" }));
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not close on a backdrop click with no preceding press", () => {
    const onClose = vi.fn();
    render(
      <Sheet open={true} onClose={onClose}>
        <div>content</div>
      </Sheet>,
    );
    fireEvent.click(screen.getByRole("dialog").parentElement!);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps the panel clipped so overflowing content cannot escape it", () => {
    render(
      <Sheet open={true} onClose={() => {}}>
        <div>content</div>
      </Sheet>,
    );
    expect(screen.getByRole("dialog").className).toContain("overflow-hidden");
  });

  it("full bleed: the panel stands on the body, not in the page it covers", () => {
    // The fullscreen surface *is* the viewport. Rendered in place, it is a
    // flow sibling of the page around it, and a `space-y-6` container gives
    // it a 24px top margin — a strip of the application showing above a
    // screen that claims to cover it.
    render(
      <div className="space-y-6">
        <p>page content</p>
        <Sheet open={true} onClose={() => {}} fullBleed aria-label="wizard">
          <div>content</div>
        </Sheet>
      </div>,
    );
    const backdrop = screen.getByRole("dialog", {
      name: "wizard",
    }).parentElement!;
    expect(backdrop.parentElement).toBe(document.body);
  });

  it("full bleed on a phone: the panel stands on the body as well", () => {
    // On a phone a floor screen — receiving, picking — is the viewport in
    // the same way, and it opens from a document page whose body is a
    // `space-y-6` column: the top 24px showed the page header under it.
    render(
      <div className="space-y-6">
        <p>page content</p>
        <Sheet
          open={true}
          onClose={() => {}}
          fullBleedOnMobile
          aria-label="receiving"
        >
          <div>content</div>
        </Sheet>
      </div>,
    );
    const backdrop = screen.getByRole("dialog", {
      name: "receiving",
    }).parentElement!;
    expect(backdrop.parentElement).toBe(document.body);
  });
});

describe("a sheet opened over another sheet", () => {
  // The class was pre-existing: with two sheets up, one Escape took both
  // (2 → 0 dialogs). That is the wrong half of a wizard whose first control
  // opens a list — the press aimed at the list threw the wizard away too,
  // and with a wizard that guards its drafts it raised a destructive
  // question over the list still standing open. One press, one layer.
  function NestedSheets({
    topDismissible = true,
  }: {
    topDismissible?: boolean;
  }) {
    const [baseOpen, setBaseOpen] = useState(true);
    const [topOpen, setTopOpen] = useState(true);
    return (
      <>
        <Sheet
          open={baseOpen}
          onClose={() => setBaseOpen(false)}
          aria-label="wizard"
        >
          <button>inside</button>
        </Sheet>
        {topOpen && (
          <Sheet
            open
            onClose={() => setTopOpen(false)}
            dismissible={topDismissible}
            aria-label="list"
          >
            <button>pick</button>
          </Sheet>
        )}
      </>
    );
  }

  it("gives the Escape to the top sheet only", () => {
    render(<NestedSheets />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(
      screen.queryByRole("dialog", { name: "list" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "wizard" })).toBeInTheDocument();
  });

  it("hands the next Escape to the sheet underneath", () => {
    render(<NestedSheets />);

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.keyDown(document, { key: "Escape" });

    expect(
      screen.queryByRole("dialog", { name: "wizard" }),
    ).not.toBeInTheDocument();
  });

  it("a top sheet that must not close swallows the press, and the one below stands idle", () => {
    render(<NestedSheets topDismissible={false} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.getByRole("dialog", { name: "list" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "wizard" })).toBeInTheDocument();
  });
});

describe("SheetBody", () => {
  it("is the scroll layer: shrinkable and vertically scrollable", () => {
    render(
      <Sheet open={true} onClose={() => {}}>
        <SheetBody data-testid="body">content</SheetBody>
      </Sheet>,
    );
    const body = screen.getByTestId("body");
    expect(body.className).toContain("overflow-y-auto");
    expect(body.className).toContain("min-h-0");
    expect(body.className).toContain("flex-1");
  });

  it("merges a caller className", () => {
    render(<SheetBody className="p-5" data-testid="body" />);
    expect(screen.getByTestId("body").className).toContain("p-5");
  });
});

describe("SheetTitle", () => {
  it("renders an h2 with the default type styles", () => {
    render(<SheetTitle>My title</SheetTitle>);
    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading).toHaveTextContent("My title");
    expect(heading.className).toContain("text-lg");
  });

  it("merges a caller className", () => {
    render(<SheetTitle className="text-base">Small</SheetTitle>);
    expect(screen.getByRole("heading", { level: 2 }).className).toContain(
      "text-base",
    );
  });
});

describe("SheetFooter", () => {
  it("keeps its place and carries the bottom safe area", () => {
    render(<SheetFooter data-testid="footer">actions</SheetFooter>);
    const footer = screen.getByTestId("footer");
    expect(footer.className).toContain("shrink-0");
    expect(footer.className).toContain("border-t");
    expect(footer.className).toContain("safe-area-inset-bottom");
  });

  it("merges a caller className", () => {
    render(<SheetFooter className="space-y-3" data-testid="footer" />);
    expect(screen.getByTestId("footer").className).toContain("space-y-3");
  });
});

describe("SheetActions", () => {
  it("states both halves of the width rule, so no call site states either", () => {
    render(<SheetActions data-testid="actions" />);
    const actions = screen.getByTestId("actions");
    // Full width on a phone…
    expect(actions.className).toContain("[&>button]:flex-1");
    // …and released from `sm:` up, which is the half a hand-written row drops.
    expect(actions.className).toContain("sm:[&>button]:flex-initial");
    expect(actions.className).toContain("justify-end");
  });

  it("merges a caller className", () => {
    render(<SheetActions className="gap-3" data-testid="actions" />);
    expect(screen.getByTestId("actions").className).toContain("gap-3");
  });
});

describe("SheetHeader", () => {
  it("renders the title inside an h2", () => {
    render(<SheetHeader title="Edit storage" />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Edit storage",
    );
  });

  it("renders no close button when onClose is omitted", () => {
    render(<SheetHeader title="No close" />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<SheetHeader title="Closable" onClose={onClose} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("labels the close button, and lets the caller override it", () => {
    const { rerender } = render(<SheetHeader onClose={() => {}} />);
    expect(screen.getByRole("button")).toHaveAccessibleName();

    rerender(<SheetHeader onClose={() => {}} closeLabel="Dismiss" />);
    expect(screen.getByRole("button")).toHaveAccessibleName("Dismiss");
  });

  it("renders children between the title and the close button", () => {
    render(
      <SheetHeader title="With slot" onClose={() => {}}>
        <span>badge</span>
      </SheetHeader>,
    );
    expect(screen.getByText("badge")).toBeInTheDocument();
  });
});

describe("Sheet inside a spaced container", () => {
  it("cancels the top margin a space-y parent would hand its overlay", () => {
    render(
      <div className="space-y-6">
        <p>Page</p>
        <Sheet open onClose={() => {}} aria-label="Edit">
          <div>content</div>
        </Sheet>
      </div>,
    );
    // The overlay is the dialog's parent; without `!m-0` it would start
    // 24px down and leave the top of the app bar undimmed and clickable.
    const overlay = screen.getByRole("dialog").parentElement as HTMLElement;
    expect(overlay.className).toContain("fixed");
    expect(overlay.className).toContain("!m-0");
  });
});
