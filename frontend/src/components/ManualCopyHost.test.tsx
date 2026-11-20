import { act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { copyTextOrExplain, manualCopyStore } from "@/lib/clipboard";
import { ActionMenu } from "@/components/ui/ActionMenu";
import ManualCopyHost from "./ManualCopyHost";

/**
 * A copy the browser refused is only recoverable if the value is on the
 * screen: the sentence "select the value" points at a field, not at a row
 * that shows eight characters of it.
 */

afterEach(() => {
  act(() => manualCopyStore.dismiss());
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
    // `setup()` installs a clipboard stub of its own, so it comes first.
    const user = userEvent.setup();
    vi.stubGlobal("navigator", { clipboard: undefined });
    render(<ManualCopyHost />);
    await act(async () => {
      await copyTextOrExplain("v", "m");
    });

    await user.click(screen.getByRole("button", { name: /done/i }));

    expect(screen.queryByTestId("manual-copy-value")).toBeNull();
  });

  it("keeps the focus in the field when the copy was asked for from a menu", async () => {
    // The menu hands focus back to its trigger in a step of its own after it
    // closes; with no clipboard there is no await gap, so the sheet has
    // already focused the field by then.
    const user = userEvent.setup();
    vi.stubGlobal("navigator", { clipboard: undefined });
    render(
      <>
        <ActionMenu
          label="Row actions"
          actions={[
            {
              id: "copy",
              label: "Copy link",
              onSelect: () => {
                void copyTextOrExplain("http://192.168.1.20/join?code=x", "m");
              },
            },
          ]}
        />
        <ManualCopyHost />
      </>,
    );

    await user.click(screen.getByRole("button", { name: "Row actions" }));
    await user.click(screen.getByRole("button", { name: "Copy link" }));

    const field = await screen.findByTestId("manual-copy-value");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(field).toHaveFocus();
  });
});
