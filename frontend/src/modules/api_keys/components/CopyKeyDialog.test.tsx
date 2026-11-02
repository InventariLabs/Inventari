import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import CopyKeyDialog from "./CopyKeyDialog";

const apiKey = {
  id: "key-1",
  name: "CI",
  raw_key: "inv_live_0123456789abcdef",
  prefix: "inv_live",
  created_at: "2026-01-01T00:00:00Z",
  expires_at: null,
  last_used_at: null,
  scopes: [],
  is_active: true,
};

function renderDialog() {
  const onClose = vi.fn();
  render(
    <CopyKeyDialog
      apiKey={
        apiKey as unknown as Parameters<typeof CopyKeyDialog>[0]["apiKey"]
      }
      onClose={onClose}
    />,
  );
  return onClose;
}

describe("CopyKeyDialog", () => {
  it("does not close on Escape", () => {
    // The key is shown once and cannot be recovered. A reflex Escape — the one
    // that closed the previous modal — used to destroy the credential with no
    // warning and no undo.
    const onClose = renderDialog();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByTestId("api-key-warning")).toBeInTheDocument();
  });

  it("does not close on a backdrop click", () => {
    const onClose = renderDialog();

    const backdrop = screen.getByRole("dialog").parentElement!;
    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);

    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes through its own button", () => {
    const onClose = renderDialog();

    fireEvent.click(screen.getByTestId("api-key-dialog-close"));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("says the key can be taken by hand when the copy does not land", async () => {
    // Outside a secure context — the usual self-hosted install over `http://`
    // — there is no clipboard at all. The key is shown once and cannot be
    // recovered, so the button that cannot copy has to point at the value
    // rather than change to "Copied!" and say nothing.
    const original = navigator.clipboard;
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      configurable: true,
    });

    try {
      renderDialog();

      fireEvent.click(
        screen.getByRole("button", { name: /copy to clipboard/i }),
      );

      expect(
        await screen.findByTestId("copy-key-manual-hint"),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /copied!/i }),
      ).not.toBeInTheDocument();
      // The value itself stays selectable either way.
      expect(screen.getByText(apiKey.raw_key)).toBeInTheDocument();
    } finally {
      Object.defineProperty(navigator, "clipboard", {
        value: original,
        configurable: true,
      });
    }
  });
});
