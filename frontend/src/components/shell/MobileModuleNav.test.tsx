import { fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { Box, Package } from "lucide-react";
import type { ModuleNavItem } from "@/lib/moduleRegistry";
import { MobileModuleNav } from "./MobileModuleNav";

const bar: ModuleNavItem[] = [
  { path: "/inventory/items", icon: Box, labelKey: "nav.items" },
  { path: "/inventory/locations", icon: Package, labelKey: "nav.storages" },
];

function renderBar() {
  return render(
    <MemoryRouter>
      <MobileModuleNav
        bar={bar}
        more={[]}
        hasBar
        isActive={(path) => path === "/inventory/items"}
      />
    </MemoryRouter>,
  );
}

describe("MobileModuleNav", () => {
  /**
   * At phone width the desktop band is `display:none`, so this bar is the only
   * navigation the document has. As a plain `<div>` it left the rotor's
   * "Landmarks" list without the application's main navigation entirely.
   */
  it("is a named navigation landmark", () => {
    renderBar();

    expect(
      screen.getByRole("navigation", { name: "Module navigation" }),
    ).toBeInTheDocument();
  });

  it("keeps its links inside that landmark", () => {
    renderBar();

    const nav = screen.getByRole("navigation");
    expect(nav.querySelectorAll("a")).toHaveLength(bar.length);
  });

  /**
   * The active item used to paint its label `text-primary-600`: on
   * surface-card that measured 3.77:1 light / 3.95:1 dark — below AA at the
   * bar's 10px, and unfixable centrally, because product profiles repaint
   * the whole primary ramp (UI_GUIDELINES §1.1). The desktop band already
   * carries "active" on weight alone for the same reason.
   */
  it("carries the active state without a brand-coloured label", () => {
    renderBar();

    const active = screen.getByRole("link", { current: "page" });
    expect(active).toHaveClass("font-semibold");
    expect(active.className).not.toMatch(/text-primary-\d/);
  });
});

describe("MobileModuleNav — the more menu", () => {
  const more: ModuleNavItem[] = [
    { path: "/inventory/categories", icon: Box, labelKey: "nav.categories" },
  ];
  const others = [{ basePath: "/recipes", displayName: "Kitchen", icon: Box }];

  function renderWithMore() {
    return render(
      <MemoryRouter>
        <MobileModuleNav
          bar={bar}
          more={more}
          hasBar
          isActive={() => false}
          otherModules={others}
        />
      </MemoryRouter>,
    );
  }

  it("opens on the More button and offers the other modules too", () => {
    renderWithMore();
    const toggle = screen.getByRole("button", { name: "More" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: /Kitchen/ })).toBeInTheDocument();
    // A second press folds it again instead of leaving it open.
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("link", { name: /Kitchen/ }),
    ).not.toBeInTheDocument();
  });

  it("folds away once a page in it, another module or a bar tab is chosen", () => {
    // A menu left open over the page it just navigated to hides the page.
    renderWithMore();
    const toggle = screen.getByRole("button", { name: "More" });

    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("link", { name: /Kitchen/ }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);
    const nav = screen.getByRole("navigation");
    const inMenu = nav.querySelector('a[href="/inventory/categories"]');
    expect(inMenu).not.toBeNull();
    fireEvent.click(inMenu as Element);
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("link", { name: /nav.items|Items/ }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
