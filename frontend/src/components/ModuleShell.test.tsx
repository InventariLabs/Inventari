import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Package } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { moduleRegistry } from "@/lib/moduleRegistry";

import ModuleShell from "./ModuleShell";
import "@/modules/warehouse/module";

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["warehouse"],
    hiddenModules: [],
    focusModule: null,
    focusStatus: "ready",
    isModuleEnabled: (name: string) => name === "warehouse",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

vi.mock("@/hooks/useHasRole", () => ({
  useRoleCheck: () => () => true,
}));

/**
 * The module tabs stick under the top bar, and under the notice strip when
 * there is one: they take the strip's height from the shell, which is zero
 * when the strip is empty, and a layer from the z-index system.
 *
 * Both bars used to stick at the same offset, so once the page scrolled one
 * covered the other — the demo notice hid the tabs, then the tabs hid the
 * notice and its "Start over" button.
 */
describe("ModuleShell — the module tabs", () => {
  it("stack under the notice strip and take their layer from the z-index system", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/warehouse"]}>
          <Routes>
            <Route
              path="/warehouse/*"
              element={<ModuleShell moduleName="warehouse" />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const tabs = screen.getByRole("navigation", { name: /module/i });
    expect(tabs.className).toContain(
      "top-[calc(3.5rem+var(--app-notice-height,0px))]",
    );
    expect(tabs.className).toContain("z-[var(--z-module-nav)]");
    expect(tabs.className).not.toMatch(/\bz-\d+\b/);
  });
});

/**
 * A module may re-skin the brand palette while its screens are on show. The
 * shell applies the variables on <html> and must give the page back exactly as
 * it found it, or the next module opens in the previous one's colours.
 */
describe("ModuleShell — a module's theme variables", () => {
  it("applies them while mounted and restores or removes them on unmount", () => {
    moduleRegistry.register({
      name: "shell-theme-test",
      routes: [],
      moduleNav: {
        basePath: "/shell-theme-test",
        items: [{ path: "/shell-theme-test", icon: Package, labelKey: "x" }],
      },
      theme: {
        cssVariables: {
          "--shell-test-had-value": "10 20 30",
          "--shell-test-was-unset": "40 50 60",
        },
      },
    });
    const root = document.documentElement;
    root.style.setProperty("--shell-test-had-value", "1 2 3");

    const { unmount } = render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/shell-theme-test"]}>
          <Routes>
            <Route
              path="/shell-theme-test/*"
              element={<ModuleShell moduleName="shell-theme-test" />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(root.style.getPropertyValue("--shell-test-had-value")).toBe(
      "10 20 30",
    );
    expect(root.style.getPropertyValue("--shell-test-was-unset")).toBe(
      "40 50 60",
    );

    unmount();

    expect(root.style.getPropertyValue("--shell-test-had-value")).toBe("1 2 3");
    expect(root.style.getPropertyValue("--shell-test-was-unset")).toBe("");
    root.style.removeProperty("--shell-test-had-value");
  });
});
