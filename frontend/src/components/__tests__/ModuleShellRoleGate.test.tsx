import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Package, Settings } from "lucide-react";
import ModuleShell from "@/components/ModuleShell";

/**
 * A nav entry the reader can click and cannot open is worse than no entry:
 * the module settings endpoint is admin-only, so a manager reached it, was
 * refused, and the refusal arrived looking like the server had broken.
 */

const mockAuthState: { user: { role: string; is_superuser: boolean } | null } =
  { user: { role: "admin", is_superuser: false } };

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof mockAuthState) => unknown) =>
    selector ? selector(mockAuthState) : mockAuthState,
}));

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
  useModules: () => ({ enabledModules: ["equipment"] }),
}));

const nav = {
  basePath: "/equipment",
  items: [
    { path: "/equipment/assets", labelKey: "Assets", icon: Package },
    { path: "/equipment/models", labelKey: "Models", icon: Package },
    {
      path: "/equipment/settings",
      labelKey: "Module settings",
      icon: Settings,
      roles: ["admin"],
    },
  ],
};

function renderShell() {
  render(
    <MemoryRouter initialEntries={["/equipment/assets"]}>
      <ModuleShell moduleName="equipment" />
    </MemoryRouter>,
  );
  // The active item's label also becomes the page title, so assertions read
  // the nav band itself rather than the whole document.
  return within(screen.getByRole("navigation"));
}

describe("role-gated module nav entries", () => {
  beforeEach(() => {
    getModuleNav.mockReset();
    getModuleNav.mockReturnValue(nav);
  });

  it("keeps the entry for the role that can open it", () => {
    mockAuthState.user = { role: "admin", is_superuser: false };
    const band = renderShell();

    expect(band.getByText("Module settings")).toBeInTheDocument();
  });

  it("hides it from a role that would only be refused", () => {
    mockAuthState.user = { role: "manager", is_superuser: false };
    const band = renderShell();

    expect(band.queryByText("Module settings")).not.toBeInTheDocument();
    expect(band.getByText("Assets")).toBeInTheDocument();
  });

  it("lets a superuser through any gate", () => {
    mockAuthState.user = { role: "user", is_superuser: true };
    const band = renderShell();

    expect(band.getByText("Module settings")).toBeInTheDocument();
  });

  it("leaves ungated entries alone", () => {
    mockAuthState.user = { role: "user", is_superuser: false };
    const band = renderShell();

    expect(band.getByText("Assets")).toBeInTheDocument();
    expect(band.getByText("Models")).toBeInTheDocument();
  });
});
