import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { AssetListHeaderActions } from "../components/AssetListHeaderActions";

function renderActions(canWrite: boolean) {
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
});
