import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Package } from "lucide-react";
import ModuleShell from "@/components/ModuleShell";

/**
 * A nav item's title and subtitle describe that item's own screen. The tab
 * underline follows the prefix, because a nested screen still belongs to its
 * section — but the header used to follow it too, so the creation form
 * introduced itself with the list's description.
 */

const getModuleNav = vi.fn();

vi.mock("@/lib/moduleRegistry", async () => {
  const actual = await vi.importActual<typeof import("@/lib/moduleRegistry")>(
    "@/lib/moduleRegistry",
  );
  return {
    ...actual,
    moduleRegistry: {
      getModuleNav: () => getModuleNav(),
      getModule: () => undefined,
      // No focus module in these tests — the shell stays with the module
      // whose route tree it is.
      getShellModule: () => null,
      getNavOverrides: () => ({}),
    },
  };
});

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({ enabledModules: ["inventory"] }),
}));

const nav = {
  basePath: "/inventory",
  items: [
    {
      path: "/inventory/items",
      labelKey: "Products",
      titleKey: "Products",
      subtitleKey: "Browse and manage products",
      icon: Package,
    },
    {
      path: "/inventory/locations",
      labelKey: "Storages",
      titleKey: "Storages",
      subtitleKey: "Where things are kept",
      icon: Package,
    },
  ],
};

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ModuleShell moduleName="inventory" />
    </MemoryRouter>,
  );
}

describe("module page header", () => {
  beforeEach(() => {
    getModuleNav.mockReset();
    getModuleNav.mockReturnValue(nav);
  });

  it("takes the title and subtitle from the screen it is on", () => {
    renderAt("/inventory/items");

    expect(
      screen.getByRole("heading", { name: "Products" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Browse and manage products")).toBeInTheDocument();
  });

  it("lends neither to a screen nested under it", () => {
    renderAt("/inventory/items/add");

    expect(
      screen.queryByText("Browse and manage products"),
    ).not.toBeInTheDocument();
  });

  it("still underlines the section a nested screen belongs to", () => {
    renderAt("/inventory/items/add");

    const tab = screen.getByRole("link", { name: /Products/ });
    expect(tab).toHaveAttribute("aria-current", "page");
  });
});
