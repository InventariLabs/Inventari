import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import NotFoundPage from "./NotFoundPage";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { MODULE_PATHS } from "@/lib/moduleRegistry/modulePaths";

const authState = {
  user: { role: "manager", is_superuser: false, permissions: [] as string[] },
  isAuthenticated: true,
  isLoading: false,
};

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof authState) => unknown) =>
    selector ? selector(authState) : authState,
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    // Neither module is on — that is the situation under test.
    enabledModules: ["core", "items"],
    isModuleEnabled: () => false,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <NotFoundPage />
    </MemoryRouter>,
  );
}

describe("NotFoundPage", () => {
  beforeEach(() => {
    authState.user = { role: "manager", is_superuser: false, permissions: [] };
  });

  it("names a module no chunk was ever loaded for", () => {
    // The answer comes from data, not from a module somebody imported: in the
    // app only enabled modules ever reach the registry, so asking it which
    // module owns a path could never name one that is off — the screen could
    // not fire at all. (The suite's global setup imports a handful of modules,
    // so the registry is no proof either way here; the table is.)
    expect(MODULE_PATHS.shopping_lists.paths).toContain("/shopping-lists");

    renderAt("/shopping-lists");

    expect(screen.getByText("Module Not Enabled")).toBeInTheDocument();
    expect(screen.queryByText("Page Not Found")).not.toBeInTheDocument();
  });

  it("answers from the table, never from the registry", () => {
    // The registry only ever holds modules somebody imported — in the app,
    // only the enabled ones — so a lookup that goes through it cannot name a
    // module that is off. Reading the table is the mechanism, and this is the
    // assertion that fails when the lookup goes back to the registry.
    const registered = vi.spyOn(moduleRegistry, "getAllRegisteredModules");

    renderAt("/shopping-lists");

    expect(registered).not.toHaveBeenCalled();
    expect(screen.getByText("Module Not Enabled")).toBeInTheDocument();
  });

  it("recognises a disabled module that has no nav of its own", () => {
    // Matching only on `basePath` meant a module whose routes are not under
    // any nav — printing's scan route — answered with a plain 404 while its
    // neighbour got the proper screen.
    renderAt("/labels/scan/abc");

    expect(screen.getByText("Module Not Enabled")).toBeInTheDocument();
    expect(screen.queryByText("Page Not Found")).not.toBeInTheDocument();
  });

  it.each(["/settings/webhooks", "/settings/api-keys"])(
    "says a module is off at %s, the address its settings section lives at",
    (path) => {
      // A module whose only screen is a settings section owned no path in the
      // table, so its address read as one that never existed — to whoever
      // followed it from a guide or a bookmark.
      renderAt(path);

      expect(screen.getByText("Module Not Enabled")).toBeInTheDocument();
      expect(screen.queryByText("Page Not Found")).not.toBeInTheDocument();
    },
  );

  it("still recognises one that does", () => {
    renderAt("/shopping-lists/anything");

    expect(screen.queryByText("Page Not Found")).not.toBeInTheDocument();
  });

  it("does not send a member to the store that refuses them", () => {
    // "Open Modules" led to /apps, which used to bounce a non-admin back to
    // the launcher without a word.
    renderAt("/shopping-lists");

    expect(
      screen.queryByRole("link", { name: /Open Modules/i }),
    ).not.toBeInTheDocument();
  });

  it("offers the store to an administrator", () => {
    authState.user = { role: "admin", is_superuser: false, permissions: [] };
    renderAt("/shopping-lists");

    expect(
      screen.getByRole("link", { name: /Open Modules/i }),
    ).toBeInTheDocument();
  });

  it("keeps the plain 404 for an address no module claims", () => {
    renderAt("/nothing-here");

    expect(screen.getByText("Page Not Found")).toBeInTheDocument();
  });
});
