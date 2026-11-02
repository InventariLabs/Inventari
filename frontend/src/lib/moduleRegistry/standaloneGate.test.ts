import { describe, it, expect } from "vitest";
import { matchRoutes } from "react-router-dom";
import { createAppRoutes } from "@/App";

import { moduleRegistry } from "../moduleRegistry";
import { RegistryQueries } from "./registryQueries";
import { resolveModuleTarget } from "./resolveModuleTarget";
import { shellRoutes } from "./shellRoutes";
import { STANDALONE_MODULE_NAMES } from "./standaloneModuleNames";
import type { AdoptableCoreSection } from "./moduleInterfaces";

/**
 * The standalone-contract gate: a module that declares it can stand alone as
 * the single focus module must account for every core section its workflow
 * touches — adopted or renounced, never silently dropped. Without this the
 * declaration is a sentence in a comment: hiding the core navigation could
 * orphan a section (the label pool, the scanner) and a printed sticker would
 * stop scanning with nothing failing a build.
 *
 * Declaring `standalone` is also what makes a module a candidate for
 * single-module mode, so the gate pins the demonstrator: equipment stands
 * entirely alone and adopts the label pool and the scanner.
 */

// Registering every real module, the same way App.tsx does.
import.meta.glob("../../modules/*/module.ts", { eager: true });

// The gate knows the full set on purpose: adding a core section a standalone
// module must account for is the deliberate act of adding it here.
const ADOPTABLE_CORE_SECTIONS: AdoptableCoreSection[] = [
  "labels",
  "scan",
  "stats",
  "stock_takes",
  "archive",
];

const CORE_NAV_SECTIONS = ["items", "storages", "categories", "stock", "moves"];

describe("standalone declaration gate", () => {
  it("keeps labels in inventory and mounts statistics only with stats enabled", () => {
    const inventory = moduleRegistry.getModule("inventory")!;
    const stats = moduleRegistry.getModule("stats")!;
    expect(inventory.routes?.map((route) => route.path)).toContain(
      "/inventory/labels",
    );
    const statsNav = inventory.moduleNav?.items.find(
      (item) => item.path === "/inventory/stats",
    );
    expect(statsNav?.requiresModules).toContain("stats");
    for (const path of [
      "/inventory/stats",
      "/inventory/stats/analytics",
      "/inventory/stats/reconciliation",
    ]) {
      expect(inventory.routes?.some((route) => route.path === path)).toBe(
        false,
      );
      const route = stats.routes?.find((entry) => entry.path === path);
      expect(route?.shell).toBe("inventory");
      const withoutStats = shellRoutes([inventory]);
      const withStats = shellRoutes([inventory, stats]);
      const mounted = (modules: typeof withoutStats.shellModules) =>
        modules[0].routes.some((entry) => entry.path === path);
      expect(mounted(withoutStats.shellModules)).toBe(false);
      expect(mounted(withStats.shellModules)).toBe(true);
    }
  });
  const standaloneModules = moduleRegistry
    .getAllRegisteredModules()
    .map((name) => moduleRegistry.getModule(name))
    .filter((mod) => mod && mod.standalone);

  it("keeps the empty-state list of standalone names equal to the declarations", () => {
    // The live registry holds enabled modules only, so the screen that tells
    // the reader what to switch on reads this list instead.
    expect([...STANDALONE_MODULE_NAMES]).toEqual(
      standaloneModules.map((mod) => mod!.name).sort(),
    );
  });

  it("offers exactly the audited standalone products in Work mode", () => {
    const all = moduleRegistry.getAllRegisteredModules();
    expect(
      moduleRegistry.getStandaloneModules(all).map((mod) => mod.name),
    ).toEqual(["equipment", "maker", "recipes", "shopping_lists", "warehouse"]);
    expect(
      moduleRegistry
        .getStandaloneModules(["partners", "stock_takes", "nutrition"])
        .map((mod) => mod.name),
    ).toEqual([]);
  });

  it("an organization still focused on stock takes keeps its home and counting routes", () => {
    // Withdrawn from the offer, not from the app: the declaration is gone, so
    // the counting pages render under the inventory shell.
    const mod = moduleRegistry.getModule("stock_takes")!;
    expect(mod.standalone).toBeUndefined();
    expect(resolveModuleTarget(mod)).toBe("/inventory/stock-takes");
    expect(
      moduleRegistry.getShellModule(
        "/inventory/stock-takes/count/counting",
        ["inventory", "stock_takes"],
        "stock_takes",
      )?.name,
    ).toBe("inventory");
  });

  it.each([
    ["/inventory/stock-takes", "stock-takes"],
    ["/inventory/stock-takes/count/counting", "stock-takes/:id/counting"],
    ["/inventory/stock-takes/count/report", "stock-takes/:id/report"],
  ])("keeps the real inventory route for %s", (pathname, expected) => {
    const inventory = moduleRegistry.getModule("inventory")!;
    const stockTakes = moduleRegistry.getModule("stock_takes")!;
    // The counting screens are stock_takes' own, hosted in the inventory
    // shell; mounted the way the app mounts them.
    const mounted = shellRoutes([inventory, stockTakes]);
    const matches = matchRoutes(
      createAppRoutes(mounted.shellModules, mounted.flatRoutes, []),
      pathname,
    );
    expect(matches?.at(-1)?.route.path).toBe(expected);
  });

  it("equipment declares it stands alone, or the contract has no demonstrator", () => {
    expect(moduleRegistry.getModule("equipment")?.standalone).toBeDefined();
  });

  standaloneModules.forEach((mod) => {
    const decl = mod!.standalone!;
    describe(mod!.name, () => {
      it("accounts for every adoptable core section — nothing silently drops", () => {
        expect(Object.keys(decl.coreSections).sort()).toEqual(
          [...ADOPTABLE_CORE_SECTIONS].sort(),
        );
        for (const section of ADOPTABLE_CORE_SECTIONS) {
          expect(["adopt", "renounce"]).toContain(decl.coreSections[section]);
        }
      });

      it("keeps only real core nav sections, each once", () => {
        const keep = decl.keepCoreNav ?? [];
        for (const section of keep) {
          expect(CORE_NAV_SECTIONS).toContain(section);
        }
        expect(new Set(keep).size).toBe(keep.length);
      });
    });
  });

  describe("equipment", () => {
    it("adopts the label pool and the scanner so a printed sticker keeps scanning", () => {
      const equipment = moduleRegistry.getModule("equipment");
      expect(equipment?.standalone?.coreSections.labels).toBe("adopt");
      expect(equipment?.standalone?.coreSections.scan).toBe("adopt");
    });

    it("stands entirely alone — keeps no core nav section", () => {
      const equipment = moduleRegistry.getModule("equipment");
      expect(equipment?.standalone?.keepCoreNav ?? []).toEqual([]);
    });
  });

  it("a kept stock entry accepts a declaring module outside the original consumers", () => {
    const inventory = moduleRegistry.getModule("inventory")!;
    const counting = {
      ...moduleRegistry.getModule("warehouse")!,
      name: "counting_extension",
    };
    const queries = new RegistryQueries(
      new Map([
        ["inventory", inventory],
        [counting.name, counting],
      ]),
      new Map(),
      new Map(),
    );
    const stock = queries
      .getKeptCoreNavItems(counting.name)
      .find((item) => item.path === "/inventory/stock");
    expect(stock).toBeDefined();
    expect(stock?.requiresModules).toContain(counting.name);
  });

  describe("recipes", () => {
    it("is offered as a focus module with embedded stock and shopping", () => {
      const offered = moduleRegistry
        .getStandaloneModules(["inventory", "equipment", "recipes"])
        .map((mod) => mod.name);
      expect(offered).toContain("recipes");
      expect(
        moduleRegistry.getModule("recipes")?.standalone?.keepCoreNav ?? [],
      ).toEqual([]);
      expect(
        moduleRegistry
          .getModule("recipes")
          ?.standalone?.backgroundFeatures?.map((feature) => feature.provider),
      ).toEqual(["inventory", "shopping_lists"]);
    });

    it("renounces every adoptable section, so no core entry beyond the kept ones", () => {
      const recipes = moduleRegistry.getModule("recipes")!;
      for (const section of ADOPTABLE_CORE_SECTIONS) {
        expect(recipes.standalone?.coreSections[section]).toBe("renounce");
      }
      const paths = moduleRegistry
        .getShellNavItems(recipes, "recipes")
        .map((item) => item.path)
        .filter((path) => path.startsWith("/inventory"));
      expect(paths).toEqual([]);
    });

    it("offers stock as a background feature without a navigation route", () => {
      const features = moduleRegistry.getBackgroundFeatures("recipes", [
        "recipes",
        "inventory",
        "shopping_lists",
      ]);
      expect(features.map((feature) => feature.feature)).toEqual([
        "stock",
        "active_list",
      ]);
      expect(moduleRegistry.getKeptCoreNavItems("recipes")).toEqual([]);
    });
  });
});
