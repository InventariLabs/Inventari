import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { Package } from "lucide-react";
import type { FrontendModule } from "@/lib/moduleRegistry";
import { ModuleTile } from "./ModuleTile";

const module = {
  id: "inventory",
  launcher: { icon: Package, displayName: "Inventory", linkTo: "/inventory" },
  routes: [],
} as unknown as FrontendModule;

function renderTile(
  statusBadge: { count: number; labelKey: string; failed?: boolean } | null,
) {
  return render(
    <MemoryRouter>
      <ModuleTile module={module} statusBadge={statusBadge} />
    </MemoryRouter>,
  );
}

describe("ModuleTile status badge", () => {
  it("says what the number counts, not just the number", () => {
    renderTile({ count: 2, labelKey: "inventory:statusBadge.needsAttention" });
    // A bare "2" on a tile says nothing; the pill names what it counts and
    // the link carries the same sentence for a hover or a screen reader.
    // Both layouts carry it: the phone layout has no room for a pill, so the
    // sentence sits under the name there, visible rather than only a title.
    // The tile translates the module's key, as the feed does an action
    // item's: a module hands over a key, never words in one language.
    expect(screen.getAllByText("2 need attention")).toHaveLength(2);
    const link = screen.getByRole("link");
    expect(link).toHaveAccessibleName(/^Inventory.*2 need attention/);
    expect(link).toHaveAttribute("title", "Inventory, 2 need attention");
  });

  it("shows no badge and no title when nothing is counted", () => {
    renderTile(null);
    expect(screen.getByRole("link")).not.toHaveAttribute("title");
  });

  it("puts a failed read into the link's accessible name", () => {
    renderTile({ count: 0, labelKey: "", failed: true });
    expect(screen.getByRole("link")).toHaveAccessibleName(
      /^Inventory.*could not be read/i,
    );
  });

  /**
   * An `aria-label` of the module's name replaced everything else the tile
   * shows — the description under it, the count — so a voice user reading
   * the card aloud named something the link did not answer to (WCAG 2.5.3).
   */
  it("takes its name from the words it shows", () => {
    const described = {
      ...module,
      launcher: { ...module.launcher, description: "Track what you have" },
    } as FrontendModule;
    render(
      <MemoryRouter>
        <ModuleTile module={described} />
      </MemoryRouter>,
    );

    const link = screen.getByRole("link");
    expect(link).not.toHaveAttribute("aria-label");
    expect(link).toHaveAccessibleName(/^Inventory\b.*Track what you have/);
  });
});
