import { describe, it, expect, vi, beforeEach } from "vitest";
import { moduleRegistry } from "./moduleRegistry";
import type { FrontendModule } from "./moduleRegistry";
import type {
  SlotContribution,
  ValidationRule,
} from "./moduleRegistry/moduleInterfaces";
import { Package } from "lucide-react";

const makeModule = (
  name: string,
  overrides: Partial<FrontendModule> = {},
): FrontendModule => ({
  name,
  routes: [],
  ...overrides,
});

describe("ModuleRegistry.register", () => {
  it("re-registers a module without throwing (HMR support)", () => {
    const mod = makeModule("test-register");
    moduleRegistry.register(mod);
    expect(() => moduleRegistry.register(mod)).not.toThrow();
  });

  it("records the module name in getAllRegisteredModules", () => {
    moduleRegistry.register(makeModule("test-listed"));
    expect(moduleRegistry.getAllRegisteredModules()).toContain("test-listed");
  });

  it("does not warn when a moduleNav item has empty path matching basePath route", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const Comp = () => null;
    moduleRegistry.register({
      name: "test-empty-navpath",
      routes: [{ path: "/empty-navpath", component: Comp }],
      moduleNav: {
        basePath: "/empty-navpath",
        items: [{ path: "", icon: Package, labelKey: "x" }],
      },
    });
    moduleRegistry.warnOrphanedNav(["test-empty-navpath"]);
    const warned = warnSpy.mock.calls.some((c) =>
      String(c[0]).includes('"test-empty-navpath"'),
    );
    expect(warned).toBe(false);
    warnSpy.mockRestore();
  });

  it("still warns when a moduleNav item truly has no matching route", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    moduleRegistry.register({
      name: "test-orphan-navpath",
      routes: [],
      moduleNav: {
        basePath: "/orphan-navpath",
        items: [{ path: "missing", icon: Package, labelKey: "x" }],
      },
    });
    moduleRegistry.warnOrphanedNav(["test-orphan-navpath"]);
    const warned = warnSpy.mock.calls.some((c) =>
      String(c[0]).includes('"test-orphan-navpath"'),
    );
    expect(warned).toBe(true);
    warnSpy.mockRestore();
  });
});

describe("ModuleRegistry.getRoutes", () => {
  const routeMod = makeModule("test-routes-mod", {
    routes: [
      { path: "/test", component: () => null },
      { path: "/test/sub", component: () => null },
    ],
  });

  beforeEach(() => {
    moduleRegistry.register(routeMod);
  });

  it("returns routes only for enabled modules", () => {
    const routes = moduleRegistry.getRoutes(["test-routes-mod"]);
    expect(routes.some((r) => r.path === "/test")).toBe(true);
    expect(routes.some((r) => r.path === "/test/sub")).toBe(true);
  });

  it("excludes routes when module is not enabled", () => {
    const routes = moduleRegistry.getRoutes([]);
    const paths = routes.map((r) => r.path);
    expect(paths).not.toContain("/test");
  });
});

describe("ModuleRegistry.getSlotComponents", () => {
  const SlotComp1 = () => null;
  const SlotComp2 = () => null;

  const slotMod = makeModule("test-slot-mod", {
    slots: [
      { slot: "dashboard_widgets", component: SlotComp1, priority: 20 },
      { slot: "dashboard_widgets", component: SlotComp2, priority: 5 },
      { slot: "global_notifications", component: SlotComp1, priority: 1 },
    ] as SlotContribution[],
  });

  beforeEach(() => {
    moduleRegistry.register(slotMod);
  });

  it("returns components for the requested slot", () => {
    const comps = moduleRegistry.getSlotComponents("dashboard_widgets", [
      "test-slot-mod",
    ]);
    expect(comps).toContain(SlotComp1);
    expect(comps).toContain(SlotComp2);
  });

  it("returns empty array for unknown slot", () => {
    const comps = moduleRegistry.getSlotComponents("nonexistent_slot", [
      "test-slot-mod",
    ]);
    expect(comps).toHaveLength(0);
  });

  it("sorts slot components by priority (ascending)", () => {
    const comps = moduleRegistry.getSlotComponents("dashboard_widgets", [
      "test-slot-mod",
    ]);
    // priority 5 = SlotComp2 first
    expect(comps[0]).toBe(SlotComp2);
    expect(comps[1]).toBe(SlotComp1);
  });

  it("excludes contributions from disabled modules", () => {
    const comps = moduleRegistry.getSlotComponents("dashboard_widgets", []);
    expect(comps).toHaveLength(0);
  });
});

describe("ModuleRegistry.getBulkActions", () => {
  const handler = vi.fn();

  const bulkMod = makeModule("test-bulk-mod", {
    bulkActions: [
      {
        id: "bulk-delete",
        labelKey: "actions.delete",
        icon: Package,
        handler,
      },
    ],
  });

  beforeEach(() => {
    moduleRegistry.register(bulkMod);
  });

  it("returns bulk actions with moduleName injected", () => {
    const actions = moduleRegistry.getBulkActions(["test-bulk-mod"]);
    const action = actions.find((a) => a.id === "bulk-delete");
    expect(action).toBeDefined();
    expect(action?.moduleName).toBe("test-bulk-mod");
  });

  it("returns empty array when module is disabled", () => {
    const actions = moduleRegistry.getBulkActions([]);
    expect(actions.find((a) => a.id === "bulk-delete")).toBeUndefined();
  });
});

describe("ModuleRegistry.getValidationRules", () => {
  const rule: ValidationRule = {
    form: "item_create",
    field: "name",
    validator: (v: unknown) => (String(v).length < 2 ? "Too short" : null),
    priority: 10,
  };

  const ruleMod = makeModule("test-rule-mod", {
    validationRules: [rule],
  });

  beforeEach(() => {
    moduleRegistry.register(ruleMod);
  });

  it("returns rules for the specified form from enabled modules", () => {
    const rules = moduleRegistry.getValidationRules("item_create", [
      "test-rule-mod",
    ]);
    expect(rules).toContain(rule);
  });

  it("does not return rules for a different form", () => {
    const rules = moduleRegistry.getValidationRules("item_edit", [
      "test-rule-mod",
    ]);
    expect(rules).not.toContain(rule);
  });

  it("does not return rules when module is disabled", () => {
    const rules = moduleRegistry.getValidationRules("item_create", []);
    expect(rules).not.toContain(rule);
  });

  it("validator function works correctly", () => {
    expect(rule.validator("ab", {})).toBeNull();
    expect(rule.validator("a", {})).toBe("Too short");
  });
});

describe("ModuleRegistry.getNavOverrides", () => {
  const overrideMod = makeModule("test-override-mod", {
    navOverrides: [{ targetPath: "/locations", hidden: true }],
  });

  beforeEach(() => {
    moduleRegistry.register(overrideMod);
  });

  it("returns nav overrides for enabled modules", () => {
    const overrides = moduleRegistry.getNavOverrides(["test-override-mod"]);
    expect(overrides.some((o) => o.targetPath === "/locations")).toBe(true);
  });

  it("returns empty array when module is disabled", () => {
    const overrides = moduleRegistry.getNavOverrides([]);
    expect(
      overrides.find((o) => o.targetPath === "/locations"),
    ).toBeUndefined();
  });
});

describe("ModuleRegistry.hasOverrides", () => {
  it("returns true for module with navOverrides", () => {
    moduleRegistry.register(
      makeModule("test-has-override", {
        navOverrides: [{ targetPath: "/items", hidden: true }],
      }),
    );
    expect(moduleRegistry.hasOverrides("test-has-override")).toBe(true);
  });

  it("returns false for module without overrides", () => {
    moduleRegistry.register(makeModule("test-no-override"));
    expect(moduleRegistry.hasOverrides("test-no-override")).toBe(false);
  });

  it("returns false for unknown module", () => {
    expect(moduleRegistry.hasOverrides("completely-nonexistent-xyz")).toBe(
      false,
    );
  });

  it("returns true for module with theme overrides", () => {
    moduleRegistry.register(
      makeModule("test-theme-override", {
        theme: { cssVariables: { "--color-primary-500": "139 69 19" } },
      }),
    );
    expect(moduleRegistry.hasOverrides("test-theme-override")).toBe(true);
  });

  it("returns false for an empty i18nOverrides declaration", () => {
    // The badge promises a change the screen would never show.
    moduleRegistry.register(
      makeModule("test-empty-i18n-override", { i18nOverrides: {} }),
    );
    expect(moduleRegistry.hasOverrides("test-empty-i18n-override")).toBe(false);
  });

  it("returns false for a theme with no variables", () => {
    moduleRegistry.register(
      makeModule("test-empty-theme-override", { theme: { cssVariables: {} } }),
    );
    expect(moduleRegistry.hasOverrides("test-empty-theme-override")).toBe(
      false,
    );
  });

  it("returns true for a module with a real i18n override", () => {
    moduleRegistry.register(
      makeModule("test-real-i18n-override", {
        i18nOverrides: { en: { "inventory:nav.items": "Assets" } },
      }),
    );
    expect(moduleRegistry.hasOverrides("test-real-i18n-override")).toBe(true);
  });
});

describe("ModuleRegistry.getVisibleModules / getOwnerModule (focus split)", () => {
  const visibleMod = makeModule("test-focus-visible", {
    moduleNav: { basePath: "/test-focus-visible", items: [] },
    launcher: { displayName: "test:focus.visible", icon: Package },
  });
  const hiddenMod = makeModule("test-focus-hidden", {
    moduleNav: { basePath: "/test-focus-hidden", items: [] },
    launcher: { displayName: "test:focus.hidden", icon: Package },
  });
  // A deeper basePath nested under visibleMod's — the longest prefix must win.
  const nestedMod = makeModule("test-focus-nested", {
    moduleNav: { basePath: "/test-focus-visible/nested", items: [] },
    launcher: { displayName: "test:focus.nested", icon: Package },
  });
  // Has a nav base path but no launcher tile at all.
  const navOnlyMod = makeModule("test-focus-nav-only", {
    moduleNav: { basePath: "/test-focus-nav-only", items: [] },
  });

  const enabled = [
    "test-focus-visible",
    "test-focus-hidden",
    "test-focus-nested",
    "test-focus-nav-only",
  ];

  beforeEach(() => {
    moduleRegistry.register(visibleMod);
    moduleRegistry.register(hiddenMod);
    moduleRegistry.register(nestedMod);
    moduleRegistry.register(navOnlyMod);
  });

  it("getVisibleModules excludes hidden modules from the listing", () => {
    const names = moduleRegistry
      .getVisibleModules(enabled, ["test-focus-hidden"])
      .map((m) => m.name);
    expect(names).toContain("test-focus-visible");
    expect(names).not.toContain("test-focus-hidden");
  });

  it("getVisibleModules matches getModulesWithLauncher when nothing is hidden", () => {
    expect(
      moduleRegistry.getVisibleModules(enabled).map((m) => m.name),
    ).toEqual(
      moduleRegistry.getModulesWithLauncher(enabled).map((m) => m.name),
    );
  });

  it("getOwnerModule still finds a hidden module's route by path", () => {
    const owner = moduleRegistry.getOwnerModule(
      "/test-focus-hidden/items",
      enabled,
    );
    expect(owner?.name).toBe("test-focus-hidden");
  });

  it("getOwnerModule matches a module with no launcher tile", () => {
    const owner = moduleRegistry.getOwnerModule(
      "/test-focus-nav-only",
      enabled,
    );
    expect(owner?.name).toBe("test-focus-nav-only");
  });

  it("getOwnerModule prefers the longest matching basePath", () => {
    const deep = moduleRegistry.getOwnerModule(
      "/test-focus-visible/nested/detail",
      enabled,
    );
    expect(deep?.name).toBe("test-focus-nested");

    const shallow = moduleRegistry.getOwnerModule(
      "/test-focus-visible/other",
      enabled,
    );
    expect(shallow?.name).toBe("test-focus-visible");
  });

  it("getOwnerModule returns null when nothing matches or the module is disabled", () => {
    expect(moduleRegistry.getOwnerModule("/nowhere", enabled)).toBeNull();
    expect(
      moduleRegistry.getOwnerModule("/test-focus-hidden/items", []),
    ).toBeNull();
  });
});

describe("ModuleRegistry.applyThemeOverrides", () => {
  const themeMod = makeModule("test-theme-mod", {
    theme: {
      cssVariables: {
        "--color-primary-500": "139 69 19",
        "--color-primary-600": "120 53 15",
      },
    },
  });

  beforeEach(() => {
    moduleRegistry.register(themeMod);
    // Reset any inline styles applied by previous test
    document.documentElement.style.removeProperty("--color-primary-500");
    document.documentElement.style.removeProperty("--color-primary-600");
  });

  it("sets CSS variables on <html> when module is enabled", () => {
    moduleRegistry.applyThemeOverrides(["test-theme-mod"]);
    expect(
      document.documentElement.style.getPropertyValue("--color-primary-500"),
    ).toBe("139 69 19");
    expect(
      document.documentElement.style.getPropertyValue("--color-primary-600"),
    ).toBe("120 53 15");
  });

  it("reverts CSS variables when module is disabled", () => {
    moduleRegistry.applyThemeOverrides(["test-theme-mod"]);
    moduleRegistry.applyThemeOverrides([]);
    expect(
      document.documentElement.style.getPropertyValue("--color-primary-500"),
    ).toBe("");
    expect(
      document.documentElement.style.getPropertyValue("--color-primary-600"),
    ).toBe("");
  });

  it("does not re-apply overrides if module is already applied", () => {
    moduleRegistry.applyThemeOverrides(["test-theme-mod"]);
    // Manually tamper with the value — second call should NOT overwrite (idempotent)
    document.documentElement.style.setProperty(
      "--color-primary-500",
      "999 999 999",
    );
    moduleRegistry.applyThemeOverrides(["test-theme-mod"]);
    // Value stays as tampered because module was already in appliedThemeModules
    expect(
      document.documentElement.style.getPropertyValue("--color-primary-500"),
    ).toBe("999 999 999");
  });
});
