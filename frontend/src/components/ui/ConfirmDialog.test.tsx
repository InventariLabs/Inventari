import axios from "axios";
import { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Sheet } from "@/components/ui/Sheet";
import { ReadableError } from "@/lib/errors";
import { withLanguage } from "@/test/mocks/i18n";

const baseProps = {
  open: true,
  title: "Delete item?",
  message: "This action cannot be undone.",
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ConfirmDialog", () => {
  it("renders nothing when closed", () => {
    render(<ConfirmDialog {...baseProps} open={false} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("stands on the confirm layer by default", () => {
    render(<ConfirmDialog {...baseProps} />);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.style.zIndex).toBe("var(--z-confirm)");
  });

  it("stands on the layer it is asked to, for a question raised from a wizard", () => {
    // Pinned to --z-confirm it would render behind the fullscreen surface
    // that asked it: invisible, and modal all the same.
    render(<ConfirmDialog {...baseProps} zIndex="fullscreen" />);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.style.zIndex).toBe("var(--z-fullscreen)");
  });

  it("renders dialog when open", () => {
    render(<ConfirmDialog {...baseProps} />);
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("Delete item?")).toBeInTheDocument();
    expect(
      screen.getByText("This action cannot be undone."),
    ).toBeInTheDocument();
  });

  it("renders default confirm and cancel labels", () => {
    render(<ConfirmDialog {...baseProps} />);
    expect(screen.getByText("Confirm")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
  });

  it("translates the default cancel label with the UI language", async () => {
    await withLanguage("pl", () => {
      render(<ConfirmDialog {...baseProps} />);
      expect(screen.getByText("Anuluj")).toBeInTheDocument();
      expect(screen.queryByText("Cancel")).not.toBeInTheDocument();
    });
  });

  it("renders custom confirm and cancel labels", () => {
    render(
      <ConfirmDialog
        {...baseProps}
        confirmLabel="Yes, delete"
        cancelLabel="No, keep"
      />,
    );
    expect(screen.getByText("Yes, delete")).toBeInTheDocument();
    expect(screen.getByText("No, keep")).toBeInTheDocument();
  });

  it("calls onConfirm when confirm button clicked", () => {
    render(<ConfirmDialog {...baseProps} />);
    fireEvent.click(screen.getByText("Confirm"));
    expect(baseProps.onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when cancel button clicked", () => {
    render(<ConfirmDialog {...baseProps} />);
    fireEvent.click(screen.getByText("Cancel"));
    expect(baseProps.onCancel).toHaveBeenCalledTimes(1);
  });

  it("does not call onCancel when dialog inner panel clicked", () => {
    render(<ConfirmDialog {...baseProps} />);
    fireEvent.click(screen.getByText("Delete item?"));
    expect(baseProps.onCancel).not.toHaveBeenCalled();
  });

  it("calls onCancel on Escape key press", () => {
    render(<ConfirmDialog {...baseProps} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(baseProps.onCancel).toHaveBeenCalledTimes(1);
  });

  it("shows danger icon when variant is danger", () => {
    render(<ConfirmDialog {...baseProps} variant="danger" />);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.querySelector("svg")).toBeInTheDocument();
  });

  it("does not show danger icon for default variant", () => {
    render(<ConfirmDialog {...baseProps} variant="default" />);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.querySelector(".bg-red-100")).not.toBeInTheDocument();
  });

  it("has correct aria attributes", () => {
    render(<ConfirmDialog {...baseProps} />);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveAttribute("aria-labelledby");
    expect(dialog).toHaveAttribute("aria-describedby");
  });

  it("stays open, keeping what was typed, when the operation fails", async () => {
    // A dialog that closed on failure looked exactly like one that succeeded:
    // the reason typed into it was gone, the delete had not happened, and the
    // only trace was a toast on its way out.
    const rejection = new axios.AxiosError();
    rejection.response = {
      data: { detail: "Server said no" },
    } as typeof rejection.response;
    const onConfirm = vi.fn().mockRejectedValue(rejection);

    render(
      <ConfirmDialog {...baseProps} onConfirm={onConfirm}>
        <input aria-label="Reason" defaultValue="Damaged in transit" />
      </ConfirmDialog>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Server said no",
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Reason")).toHaveValue("Damaged in transit");
    expect(baseProps.onCancel).not.toHaveBeenCalled();
  });

  it("shows a ReadableError as written", async () => {
    // Not every failure is a failed request. A bulk endpoint can answer 200
    // having done nothing the reader asked for, and the sentence explaining
    // that is composed by the caller in the reader's language — so it is
    // shown as it is, where `extractApiError` would have replaced it with
    // the generic fallback.
    const onConfirm = vi
      .fn()
      .mockRejectedValue(new ReadableError("Blocked by 2 documents"));

    render(<ConfirmDialog {...baseProps} onConfirm={onConfirm} />);

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Blocked by 2 documents",
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("leaves a synchronous confirm alone", async () => {
    // Most confirmations cannot fail and close on the click, as Radix does by
    // default — only a returned promise changes that.
    const onConfirm = vi.fn();
    render(<ConfirmDialog {...baseProps} onConfirm={onConfirm} />);

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(onConfirm).toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not report a confirm-triggered close as a cancellation", () => {
    // A synchronous confirm lets Radix close the dialog, and that close also
    // arrives through onOpenChange — so the answer used to be followed by
    // onCancel from the same click. A consumer whose cancel means "the
    // reader declined" (revert the choice) then saw the refusal applied
    // right after the confirmation.
    render(<ConfirmDialog {...baseProps} />);

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(baseProps.onConfirm).toHaveBeenCalledTimes(1);
    expect(baseProps.onCancel).not.toHaveBeenCalled();
  });

  it("still reports a cancellation after a synchronous confirm that left the question open", async () => {
    // The confirming click is not the only way a synchronous confirm ends: it
    // can start work whose close rides on a later success (mutate(..., {
    // onSuccess: close })). When that work fails the question stays open, and
    // the cancel button and Escape must still mean "leave it unanswered" — an
    // answer flag latched past the click made the open dialog a modal trap
    // with no way out but a reload.
    const onConfirm = vi.fn(); // synchronous, and the dialog stays open
    render(<ConfirmDialog {...baseProps} onConfirm={onConfirm} />);

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    // The suppression window is the confirming click; flush its microtask.
    await Promise.resolve();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(baseProps.onCancel).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(baseProps.onCancel).toHaveBeenCalledTimes(2);
  });

  it("removes Escape listener when unmounted", () => {
    const { unmount } = render(<ConfirmDialog {...baseProps} />);
    unmount();
    // Firing Escape after unmount should NOT call onCancel
    fireEvent.keyDown(document, { key: "Escape" });
    expect(baseProps.onCancel).not.toHaveBeenCalled();
  });

  afterEach(() => {
    // Clean up any leftover keydown listeners from the component
    // (component itself does cleanup on unmount, this just guards tests)
  });
});

/**
 * Where the focus goes when the question is answered.
 *
 * Measured in a browser: refusing the discard question — "Keep editing" —
 * left focus on the document body, outside the sheet that asked it. Three
 * Tabs from there walked the page behind the screen ("Skip to content",
 * "Back", "Inventory") instead of the form the reader had just returned to.
 * The question is Radix's `alertdialog`, and its default is to hand focus
 * back to whatever was focused when it opened — which, when that element sat
 * in a list that closed while the question stood, no longer exists.
 */
describe("ConfirmDialog — focus on the way out", () => {
  function SheetWithQuestion({
    removeField = false,
  }: {
    removeField?: boolean;
  }) {
    const [fieldMounted, setFieldMounted] = useState(true);
    const [asking, setAsking] = useState(false);
    return (
      <Sheet open onClose={() => {}} aria-label="Create storage">
        {fieldMounted && <input aria-label="Name" defaultValue="Workshop" />}
        <button
          onClick={() => {
            setAsking(true);
            if (removeField) setFieldMounted(false);
          }}
        >
          close
        </button>
        <ConfirmDialog
          open={asking}
          title="Discard this new storage?"
          message="The name will be lost."
          onConfirm={() => setAsking(false)}
          onCancel={() => setAsking(false)}
        />
      </Sheet>
    );
  }

  it("gives focus back to the field the question took it from", async () => {
    render(<SheetWithQuestion />);
    const input = screen.getByLabelText("Name");
    input.focus();

    fireEvent.click(screen.getByRole("button", { name: "close" }));
    expect(document.activeElement).not.toBe(input);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    // Radix hands the focus back on the next task, not in the click itself.
    await waitFor(() => expect(document.activeElement).toBe(input));
  });

  it("falls back to the panel of the sheet under it when the field is gone", async () => {
    render(<SheetWithQuestion removeField />);
    const input = screen.getByLabelText("Name");
    input.focus();

    fireEvent.click(screen.getByRole("button", { name: "close" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("dialog", { name: "Create storage" }),
      ),
    );
  });
});

describe("ConfirmDialog — unmounted while closing", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts no focus timer once it has been torn down", () => {
    vi.useFakeTimers();
    const props = {
      title: "T",
      message: "M",
      onConfirm: vi.fn(),
      onCancel: vi.fn(),
    };
    const { rerender, unmount } = render(<ConfirmDialog {...props} open />);
    rerender(<ConfirmDialog {...props} open={false} />);
    unmount();

    // Radix reports the close on a task of its own, after the unmount.
    vi.advanceTimersByTime(0);

    expect(vi.getTimerCount()).toBe(0);
  });
});
