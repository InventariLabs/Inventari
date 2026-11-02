import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import SettingsDataTab from "./SettingsDataTab";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

// One knob, flipped per test: the tab reads `items:write` to decide whether
// the bulk import tile exists at all.
const rights = vi.hoisted(() => ({ itemsWrite: true }));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: (moduleName: string) =>
    moduleName === "items" ? rights.itemsWrite : true,
}));

function renderTab() {
  return render(
    <MemoryRouter initialEntries={["/settings"]}>
      <Routes>
        <Route path="/settings" element={<SettingsDataTab />} />
        <Route path="/inventory/items" element={<div>products list</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SettingsDataTab", () => {
  afterEach(() => {
    rights.itemsWrite = true;
  });

  it("hides the import tile from a role that cannot add products", () => {
    // The backend refuses a read-only account on /items/import — the tile
    // must not walk it to a wizard that refuses every row.
    rights.itemsWrite = false;
    renderTab();

    expect(screen.queryByText("Import")).not.toBeInTheDocument();
    // The export is a read — it stays.
    expect(screen.getByText("Export")).toBeInTheDocument();
  });

  it("offers the import tile to a role that may write products", () => {
    renderTab();

    expect(screen.getByText("Import")).toBeInTheDocument();
  });
  it("leads to the import wizard instead of promising it later", () => {
    // The card answered "Import will be available soon!" while the wizard —
    // XLSX / CSV / Grocy — sat two clicks away on the products list.
    renderTab();

    fireEvent.click(screen.getByText("Import"));

    expect(screen.getByText("products list")).toBeInTheDocument();
  });

  it("has no button that only looks disabled", () => {
    // `opacity-50 cursor-not-allowed` without `disabled`: greyed out to the
    // eye, focusable and clickable to everything else, including a screen
    // reader.
    renderTab();

    for (const button of screen.getAllByRole("button")) {
      // Unprefixed classes only: `disabled:opacity-50` in the Button base is
      // the honest kind — it applies when the button really is disabled.
      const classes = button.className.split(/\s+/);
      const looksDisabled =
        classes.includes("opacity-50") ||
        classes.includes("cursor-not-allowed");
      if (looksDisabled) {
        expect(button).toBeDisabled();
      }
    }
  });
});
