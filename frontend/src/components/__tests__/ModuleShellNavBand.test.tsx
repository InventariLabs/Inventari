import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Package } from "lucide-react";
import ModuleShell from "@/components/ModuleShell";

/**
 * The nav bar appears from two items up — a tab that selects the module's only
 * page is noise. But a single-screen module's content used to start ~44px
 * higher than every other module's, which read as an unfinished shell, so the
 * band's height is reserved either way (UI_GUIDELINES §2.14).
 */

const getModuleNav = vi.fn();

vi.mock("@/lib/moduleRegistry", async () => {
  const actual = await vi.importActual<typeof import("@/lib/moduleRegistry")>(
    "@/lib/moduleRegistry",
  );
  return {
    ...actual,
    moduleRegistry: {
      getModuleNav: (name: string) => getModuleNav(name),
      getModule: () => undefined,
      // No focus module in these tests — the shell stays with the module
      // whose route tree it is.
      getShellModule: () => null,
      getNavOverrides: () => ({}),
    },
  };
});

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({ enabledModules: ["warehouse"] }),
}));

function navWith(count: number) {
  return {
    basePath: "/warehouse",
    items: Array.from({ length: count }, (_, i) => ({
      path: `/warehouse/documents/tab${i}`,
      labelKey: `tab${i}`,
      icon: Package,
    })),
  };
}

function renderShell() {
  return render(
    <MemoryRouter initialEntries={["/warehouse/documents/tab0"]}>
      <ModuleShell moduleName="warehouse" />
    </MemoryRouter>,
  );
}

describe("module nav band", () => {
  beforeEach(() => getModuleNav.mockReset());

  it("renders the tab bar for a module with several screens", () => {
    getModuleNav.mockReturnValue(navWith(3));
    const { container } = renderShell();

    expect(screen.getByRole("navigation")).toBeInTheDocument();
    expect(container.querySelector('[aria-hidden="true"].h-11')).toBeNull();
  });

  it("reserves the band's height for a single-screen module", () => {
    getModuleNav.mockReturnValue(navWith(1));
    const { container } = renderShell();

    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    const spacer = container.querySelector('[aria-hidden="true"].h-11');
    expect(spacer).not.toBeNull();
    // Same vertical box as the bar it stands in for.
    expect(spacer?.className).toContain("mb-4");
    expect(spacer?.className).toContain("md:mb-6");
  });
});
