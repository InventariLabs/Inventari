import { describe, expect, it } from "vitest";

import { moduleRegistry } from "../moduleRegistry";

// Registering every real module, the same way App.tsx does.
import.meta.glob("../../modules/*/module.ts", { eager: true });

/**
 * A tab hidden on a phone must be reachable another way.
 *
 * `showOnMobile: false` removes a module's tab from the phone's bottom bar and
 * its More sheet. Supplier prices, reorder rules, order templates, ingredient
 * data and the equipment settings were hidden that way with no link anywhere
 * else, so on a phone they opened only from a typed address, and Purchase
 * Orders was left with a single item and so with no navigation at all.
 *
 * A hidden tab therefore has to be named here with the screen that links to
 * it, and the entry has to stay true: one that no longer matches a hidden tab
 * fails as well, so the list cannot go stale.
 */
const HIDDEN_ON_PURPOSE: Record<string, string> = {
  // The board is the desk's view; a phone's Start screen is the same work,
  // and /warehouse/board redirects there.
  "/warehouse/board": "redirects to the to-do screen on a phone",
};

function hiddenTabs(): string[] {
  return (
    moduleRegistry
      .getAllRegisteredModules()
      .flatMap((name) => moduleRegistry.getModuleNav(name)?.items ?? [])
      .filter((item) => item.showOnMobile === false)
      // A page that is not a desktop tab either is linked from another screen
      // and only names itself for the shell.
      .filter((item) => item.showOnDesktop !== false)
      .map((item) => item.path)
      .sort()
  );
}

describe("tabs hidden on a phone", () => {
  it("are each named with the way a phone reaches them", () => {
    expect(hiddenTabs()).toEqual(Object.keys(HIDDEN_ON_PURPOSE).sort());
  });

  it("leaves Purchase Orders with a bar and a More sheet", () => {
    const items = moduleRegistry.getModuleNav("purchase_orders")?.items ?? [];
    const onPhone = items.filter((i) => i.showOnMobile !== false);
    expect(onPhone.map((i) => i.path).sort()).toEqual(
      items.map((i) => i.path).sort(),
    );
    expect(onPhone.some((i) => i.mobileBar)).toBe(true);
    expect(onPhone.some((i) => !i.mobileBar)).toBe(true);
  });
});
