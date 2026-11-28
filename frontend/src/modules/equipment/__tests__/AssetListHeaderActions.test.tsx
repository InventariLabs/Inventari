import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, afterEach } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { AssetListHeaderActions } from "../components/AssetListHeaderActions";
import { onePreparedAtATime } from "@/modules/shared/lib/exportProgress";

function renderActions(canWrite: boolean, canExport = true) {
  signInWith(canExport ? ["items:read"] : []);
  const onExport = vi.fn();
  const onImport = vi.fn();
  render(
    <MemoryRouter>
      <AssetListHeaderActions
        canWrite={canWrite}
        onExport={onExport}
        onImport={onImport}
      />
    </MemoryRouter>,
  );
  return { onExport, onImport };
}

describe("AssetListHeaderActions", () => {
  afterEach(signOut);

  it("keeps Export and Import named for assistive technology, and Add beside them", async () => {
    const user = userEvent.setup();
    const { onExport, onImport } = renderActions(true);

    // Below `sm:` the visible label is hidden; the accessible name stays.
    await user.click(screen.getByRole("button", { name: "Export" }));
    await user.click(screen.getByRole("button", { name: "Import" }));
    expect(onExport).toHaveBeenCalledTimes(1);
    expect(onImport).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: /Add Asset/ })).toHaveAttribute(
      "href",
      "/equipment/add",
    );
  });

  it("offers a reader Export alone", () => {
    renderActions(false);

    expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Import" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Add Asset/ }),
    ).not.toBeInTheDocument();
  });

  it("shows Export busy while the equipment export is being prepared", async () => {
    let finish!: () => void;
    renderActions(true);
    const button = screen.getByRole("button", { name: "Export" });
    let running!: Promise<void>;

    act(() => {
      running = onePreparedAtATime(
        "eq-export",
        () =>
          new Promise<void>((resolve) => {
            finish = resolve;
          }),
      );
    });

    expect(button).toBeDisabled();
    expect(button.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Import" })).toBeEnabled();
    await act(async () => {
      finish();
      await running;
    });
    expect(button).toBeEnabled();
  });

  it("disables Export, with the reason, for an account the export would refuse", async () => {
    const user = userEvent.setup();
    const { onExport } = renderActions(false, false);

    const button = screen.getByRole("button", { name: "Export" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(/cannot export the asset list/);
    await user.click(button);
    expect(onExport).not.toHaveBeenCalled();
  });
});
