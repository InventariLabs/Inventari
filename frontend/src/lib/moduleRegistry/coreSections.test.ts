import { describe, it, expect } from "vitest";
import { Package } from "lucide-react";

import { moduleRegistry, getCoreSectionForPath } from "../moduleRegistry";
import {
  CORE_NAV_SECTION_PATHS,
  CORE_SECTION_NAV,
  CORE_SECTION_PATH_PREFIXES,
  getCoreNavSectionForPath,
} from "./coreSections";
import type { AdoptableCoreSection, FrontendModule } from "./moduleInterfaces";

// Registering every real module, the same way App.tsx does — the adoption
// cases below pin the real equipment declaration, not a stand-in of it.
import.meta.glob("../../modules/*/module.ts", { eager: true });

const makeModule = (
  name: string,
  overrides: Partial<FrontendModule> = {},
): FrontendModule => ({
  name,
  routes: [],
  ...overrides,
});

describe("core section map", () => {
  it("covers every adoptable section, in paths and nav alike", () => {
    const sections: AdoptableCoreSection[] = [
      "labels",
      "scan",
      "stats",
      "stock_takes",
      "archive",
    ];
    expect(Object.keys(CORE_SECTION_PATH_PREFIXES).sort()).toEqual(
      [...sections].sort(),
    );
    expect(Object.keys(CORE_SECTION_NAV).sort()).toEqual([...sections].sort());
    for (const section of sections) {
      expect(CORE_SECTION_PATH_PREFIXES[section].length).toBeGreaterThan(0);
    }
  });
});

describe("getCoreSectionForPath", () => {
  it("maps every adoptable section's paths to its section", () => {
    expect(getCoreSectionForPath("/inventory/labels")).toBe("labels");
    expect(getCoreSectionForPath("/inventory/scan")).toBe("scan");
    expect(getCoreSectionForPath("/labels/scan")).toBe("scan");
    expect(getCoreSectionForPath("/inventory/stats")).toBe("stats");
    expect(getCoreSectionForPath("/inventory/stock-takes")).toBe("stock_takes");
    expect(getCoreSectionForPath("/inventory/items/archived")).toBe("archive");
    expect(getCoreSectionForPath("/inventory/locations/archived")).toBe(
      "archive",
    );
  });

  it("keeps sub-pages inside their section", () => {
    expect(getCoreSectionForPath("/inventory/scan?code=EQP-123")).toBe("scan");
    expect(getCoreSectionForPath("/labels/scan/EQP-123")).toBe("scan");
    expect(getCoreSectionForPath("/inventory/stock-takes/abc/counting")).toBe(
      "stock_takes",
    );
  });

  it("returns null for paths no adoptable section claims", () => {
    expect(getCoreSectionForPath("/inventory")).toBeNull();
    expect(getCoreSectionForPath("/inventory/items")).toBeNull();
    expect(getCoreSectionForPath("/equipment/assets")).toBeNull();
    expect(getCoreSectionForPath("/settings")).toBeNull();
  });

  it("does not let the archive swallow the plain lists it hangs under", () => {
    // The storages/items lists prefix the archive paths only in prose, not in
    // the map — a prefix matcher ordered wrongly would claim them.
    expect(getCoreSectionForPath("/inventory/locations")).toBeNull();
    expect(getCoreSectionForPath("/inventory/items/42")).toBeNull();
  });
});

describe("RegistryQueries.getShellModule", () => {
  const enabled = ["equipment", "inventory"];

  it("hands an adopted core section to the focus module", () => {
    expect(
      moduleRegistry.getShellModule("/inventory/labels", enabled, "equipment")
        ?.name,
    ).toBe("equipment");
    expect(
      moduleRegistry.getShellModule("/inventory/scan", enabled, "equipment")
        ?.name,
    ).toBe("equipment");
  });

  it("adopts printing's flat scan route, the one entry a sticker has", () => {
    expect(
      moduleRegistry.getShellModule(
        "/labels/scan/EQP-123",
        enabled,
        "equipment",
      )?.name,
    ).toBe("equipment");
  });

  it("leaves a renounced section with its owning module", () => {
    // Equipment renounces stats — the page keeps the inventory shell.
    expect(
      moduleRegistry.getShellModule("/inventory/stats", enabled, "equipment")
        ?.name,
    ).toBe("inventory");
  });

  it("keeps the focus module on its own paths", () => {
    expect(
      moduleRegistry.getShellModule("/equipment/assets", enabled, "equipment")
        ?.name,
    ).toBe("equipment");
  });

  it("falls back to pure ownership when there is no focus module", () => {
    expect(
      moduleRegistry.getShellModule("/inventory/labels", enabled, null)?.name,
    ).toBe("inventory");
    expect(
      moduleRegistry.getShellModule("/inventory/labels", enabled)?.name,
    ).toBe("inventory");
  });

  it("falls back to pure ownership when the focus module is not enabled", () => {
    expect(
      moduleRegistry.getShellModule(
        "/inventory/labels",
        ["inventory"],
        "equipment",
      )?.name,
    ).toBe("inventory");
  });

  it("ignores a focus module that never declared standalone", () => {
    // Inventory declares no standalone — focusing on it must not reroute
    // equipment's screens.
    expect(
      moduleRegistry.getShellModule("/equipment/assets", enabled, "inventory")
        ?.name,
    ).toBe("equipment");
  });

  it("pins that a hidden module keeps its shell, an adopted section never gets the owner's", () => {
    // Case 1: focus mode hides inventory from the listings, but a direct link
    // into it still renders under the inventory shell.
    expect(
      moduleRegistry.getShellModule("/inventory/items", enabled, "equipment")
        ?.name,
    ).toBe("inventory");
    // Case 2: the adopted label pool renders under the equipment shell — not
    // under inventory, the module that owns the path.
    const shell = moduleRegistry.getShellModule(
      "/inventory/labels",
      enabled,
      "equipment",
    );
    expect(shell?.name).toBe("equipment");
    expect(shell?.name).not.toBe("inventory");
  });
});

describe("RegistryQueries.getAdoptedCoreNavItems", () => {
  it("returns the label pool and scanner entries for equipment", () => {
    const items = moduleRegistry.getAdoptedCoreNavItems("equipment");
    expect(items.map((item) => item.path)).toEqual([
      "/inventory/labels",
      "/inventory/scan",
    ]);
    expect(items).toEqual([CORE_SECTION_NAV.labels, CORE_SECTION_NAV.scan]);
  });

  it("returns nothing for a module without a standalone declaration", () => {
    expect(moduleRegistry.getAdoptedCoreNavItems("inventory")).toEqual([]);
  });
});

describe("RegistryQueries.getShellNavItems", () => {
  const focus = makeModule("test-shell-focus", {
    routes: [
      { path: "/test-shell-focus", component: () => null },
      { path: "/inventory/labels", component: () => null },
    ],
    moduleNav: {
      basePath: "/test-shell-focus",
      items: [
        { path: "/test-shell-focus", icon: Package, labelKey: "test:home" },
        // A module that one day lists an adopted section statically must not
        // get the tab twice.
        {
          path: "/inventory/labels",
          icon: Package,
          labelKey: "test:labels",
        },
      ],
    },
    standalone: {
      coreSections: {
        labels: "adopt",
        scan: "adopt",
        stats: "renounce",
        stock_takes: "renounce",
        archive: "renounce",
      },
      keepCoreNav: [],
    },
  });
  moduleRegistry.register(focus);

  it("appends adopted sections only for the focus module, deduped by path", () => {
    const paths = moduleRegistry
      .getShellNavItems(focus, "test-shell-focus")
      .map((item) => item.path);
    expect(paths).toEqual([
      "/test-shell-focus",
      "/inventory/labels",
      "/inventory/scan",
    ]);
  });

  it("returns the module's own items untouched when it is not the focus", () => {
    const items = moduleRegistry.getShellNavItems(focus, "equipment");
    expect(items).toEqual(focus.moduleNav!.items);
  });
});

describe("keepCoreNav", () => {
  const renounceAll: Record<AdoptableCoreSection, "renounce"> = {
    labels: "renounce",
    scan: "renounce",
    stats: "renounce",
    stock_takes: "renounce",
    archive: "renounce",
  };
  const keeper = makeModule("test-keeper", {
    routes: [{ path: "/test-keeper", component: () => null }],
    moduleNav: {
      basePath: "/test-keeper",
      items: [{ path: "/test-keeper", icon: Package, labelKey: "test:home" }],
    },
    standalone: {
      coreSections: renounceAll,
      keepCoreNav: ["items", "stock"],
    },
  });
  moduleRegistry.register(keeper);
  const enabled = ["inventory", "test-keeper"];

  it("shows the kept core entries beside the module's own, and nothing else", () => {
    const paths = moduleRegistry
      .getShellNavItems(keeper, "test-keeper")
      .map((item) => item.path);
    expect(paths).toEqual([
      "/test-keeper",
      "/inventory/items",
      "/inventory/stock",
    ]);
  });

  it("borrows the inventory entries, keeping their visibility rules", () => {
    const stock = moduleRegistry
      .getKeptCoreNavItems("test-keeper")
      .find((item) => item.path === "/inventory/stock");
    expect(stock?.requiresModules?.length).toBeGreaterThan(0);
  });

  it("leaves equipment unchanged: an empty keepCoreNav adds no core entry", () => {
    expect(moduleRegistry.getKeptCoreNavItems("equipment")).toEqual([]);
    const equipment = moduleRegistry.getModule("equipment")!;
    const paths = moduleRegistry
      .getShellNavItems(equipment, "equipment")
      .map((item) => item.path);
    expect(paths).not.toContain("/inventory/items");
    expect(paths).not.toContain("/inventory/stock");
  });

  it("renders a kept section under the focus module's banner", () => {
    for (const path of [
      "/inventory/items",
      "/inventory/items/42",
      "/inventory/items/add",
      "/inventory/stock",
      "/inventory/lots/7",
    ]) {
      expect(
        moduleRegistry.getShellModule(path, enabled, "test-keeper")?.name,
      ).toBe("test-keeper");
    }
  });

  it("leaves a section that is neither kept nor adopted with its owner", () => {
    for (const path of [
      "/inventory/locations",
      "/inventory/moves",
      "/inventory/categories",
      "/inventory/stock-takes",
      "/inventory/items/archived",
    ]) {
      expect(
        moduleRegistry.getShellModule(path, enabled, "test-keeper")?.name,
      ).toBe("inventory");
    }
  });

  it("does not hand kept sections to a module that is not in focus", () => {
    expect(
      moduleRegistry.getShellModule("/inventory/items", enabled, null)?.name,
    ).toBe("inventory");
    expect(
      moduleRegistry.getShellModule("/inventory/items", enabled, "equipment")
        ?.name,
    ).toBe("inventory");
  });

  it("maps every core nav section to a real inventory nav entry and route", () => {
    const inventory = moduleRegistry.getModule("inventory")!;
    const navPaths = inventory.moduleNav!.items.map((item) => item.path);
    for (const [section, { entry, prefixes }] of Object.entries(
      CORE_NAV_SECTION_PATHS,
    )) {
      expect(navPaths, section).toContain(entry);
      expect(getCoreNavSectionForPath(entry), section).toBe(section);
      expect(prefixes.length).toBeGreaterThan(0);
    }
  });

  it("does not let stock claim stock-takes", () => {
    expect(getCoreNavSectionForPath("/inventory/stock-takes")).toBeNull();
    expect(getCoreNavSectionForPath("/inventory/stock?x=1")).toBe("stock");
  });
});
