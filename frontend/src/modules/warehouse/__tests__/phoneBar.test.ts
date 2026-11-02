import { describe, expect, it } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import "../module";
import warehouseEn from "../i18n/en.json";
import inventoryEn from "@/modules/inventory/i18n/en.json";
import warehousePl from "../i18n/pl.json";
import inventoryPl from "@/modules/inventory/i18n/pl.json";
import warehouseDe from "../i18n/de.json";
import inventoryDe from "@/modules/inventory/i18n/de.json";
import warehouseFr from "../i18n/fr.json";
import inventoryFr from "@/modules/inventory/i18n/fr.json";
import warehouseEs from "../i18n/es.json";
import inventoryEs from "@/modules/inventory/i18n/es.json";
import warehousePt from "../i18n/pt.json";
import inventoryPt from "@/modules/inventory/i18n/pt.json";

const items = moduleRegistry.getModule("warehouse")?.moduleNav?.items ?? [];
const byOrder = (a: (typeof items)[number], b: (typeof items)[number]) =>
  (a.order ?? 100) - (b.order ?? 100);
const byMobileOrder = (a: (typeof items)[number], b: (typeof items)[number]) =>
  (a.mobileOrder ?? a.order ?? 100) - (b.mobileOrder ?? b.order ?? 100);

// The module menu is the things the warehouse's day is made of. A phone
// keeps the three it works from in the bottom bar; configuration and the
// desk's board sit behind it / wait for a wider screen.
describe("the warehouse module's navigation", () => {
  it("has Start, Board, History, Codes and labels and Configuration on a desktop, in that order", () => {
    expect(
      items
        .filter((item) => item.showOnDesktop !== false)
        .sort(byOrder)
        .map((item) => item.path),
    ).toEqual([
      "/warehouse/todo",
      "/warehouse/board",
      "/warehouse/history",
      "/warehouse/location-settings",
      "/warehouse/settings",
    ]);
  });

  it("puts Start, Scan and History in a phone's bottom bar", () => {
    expect(
      items
        .filter((item) => item.showOnMobile !== false && item.mobileBar)
        .sort(byMobileOrder)
        .map((item) => item.path),
    ).toEqual(["/warehouse/todo", "/warehouse/scan", "/warehouse/history"]);
  });

  it("keeps the shelf codes and Configuration in the phone's module menu and the board off it", () => {
    const more = items
      .filter((item) => item.showOnMobile !== false && !item.mobileBar)
      .sort(byMobileOrder)
      .map((item) => item.path);
    expect(more).toEqual([
      "/warehouse/location-settings",
      "/warehouse/settings",
    ]);
    expect(
      items.find((item) => item.path === "/warehouse/board")?.showOnMobile,
    ).toBe(false);
  });

  it("counts the approvals waiting on Start, where they are tasks", () => {
    const start = items.find((item) => item.path === "/warehouse/todo");
    expect(start?.Badge).toBeDefined();
    expect(
      items.find((item) => item.path === "/warehouse/approvals"),
    ).toBeUndefined();
  });
});

// The bar used to carry nine tabs; five of them became links inside Start,
// History and Configuration. A bookmark to any of them still opens a screen.
describe("the addresses the nine-tab bar linked to", () => {
  const routes = new Set(
    (moduleRegistry.getModule("warehouse")?.routes ?? []).map((r) => r.path),
  );

  it.each([
    "/warehouse",
    "/warehouse/todo",
    "/warehouse/approvals",
    "/warehouse/register",
    "/warehouse/scan",
    "/warehouse/templates",
    "/warehouse/putaway-rules",
    "/warehouse/periods",
    "/warehouse/settings",
  ])("%s still has a route", (path) => {
    expect(routes.has(path)).toBe(true);
  });
});

// A one-module Warehouse phone keeps the inventory's own Scan tab beside the
// warehouse's: two tabs reading "Scan", one for documents and one for
// products. Every language labels the document one by what it scans.
describe("the two scan tabs of a one-module phone", () => {
  const warehouse = {
    en: warehouseEn,
    pl: warehousePl,
    de: warehouseDe,
    fr: warehouseFr,
    es: warehouseEs,
    pt: warehousePt,
  };
  const inventory = {
    en: inventoryEn,
    pl: inventoryPl,
    de: inventoryDe,
    fr: inventoryFr,
    es: inventoryEs,
    pt: inventoryPt,
  };

  it.each(Object.keys(warehouse) as (keyof typeof warehouse)[])(
    "%s: the document scan tab is not labelled like the product scan tab",
    (language) => {
      expect(warehouse[language].navigation.scan).not.toBe(
        inventory[language].nav.scan,
      );
    },
  );
});
