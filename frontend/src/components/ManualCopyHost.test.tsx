import { act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { copyTextOrExplain, manualCopyStore } from "@/lib/clipboard";
import ManualCopyHost from "./ManualCopyHost";

/**
 * A copy the browser refused is only recoverable if the value is on the
 * screen: the sentence "select the value" points at a field, not at a row
 * that shows eight characters of it.
 */

afterEach(() => {
  manualCopyStore.dismiss();
  vi.unstubAllGlobals();
});

describe("ManualCopyHost", () => {
  it("shows nothing until a copy is refused", () => {
    render(<ManualCopyHost />);

    expect(screen.queryByTestId("manual-copy-value")).toBeNull();
  });

  it("shows the full value to select when the clipboard is missing", async () => {
    vi.stubGlobal("navigator", { clipboard: undefined });
    render(<ManualCopyHost />);
    const link = "http://192.168.1.20:5173/join?code=abcdefghijklmnop";

    await act(async () => {
      await copyTextOrExplain(link, "select it and copy it by hand");
    });

    expect(screen.getByTestId("manual-copy-value")).toHaveValue(link);
    expect(screen.getByText("select it and copy it by hand")).toBeVisible();
  });

  it("closes on Done", async () => {
    vi.stubGlobal("navigator", { clipboard: undefined });
    const user = userEvent.setup();
    render(<ManualCopyHost />);
    await act(async () => {
      await copyTextOrExplain("v", "m");
    });

    await user.click(screen.getByRole("button", { name: /done/i }));

    expect(screen.queryByTestId("manual-copy-value")).toBeNull();
  });
});
