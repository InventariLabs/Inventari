import { afterEach, describe, expect, it, vi } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { screensOf } from "./screensOf";

// Registering every real module, the same way App.tsx does.
import.meta.glob("../../modules/*/module.ts", { eager: true });

const WAREHOUSE_NAV = ["/warehouse/todo", "/warehouse/history"];
const INVENTORY_NAV = ["/inventory/items", "/inventory/locations"];

const nav = (basePath: string, paths: string[]) => ({
  basePath,
  items: paths.map((path) => ({ path })),
});

describe("screensOf", () => {
  afterEach(() => vi.restoreAllMocks());

  it("does not count the warehouse root, which only redirects to History", () => {
    const screens = screensOf(["warehouse"], nav("/warehouse", WAREHOUSE_NAV));
    expect(screens("/warehouse")).toBe(false);
    expect(screens("/warehouse/history")).toBe(true);
  });

  it("counts a module root its own navigation lists", () => {
    const screens = screensOf(
      ["maker"],
      nav("/maker", ["/maker", "/maker/boms"]),
    );
    expect(screens("/maker")).toBe(true);
  });

  it("does not take the folder of a spelled-out route for an id", () => {
    const screens = screensOf(
      ["inventory", "spaces"],
      nav("/inventory", INVENTORY_NAV),
    );
    expect(screens("/inventory/locations/zone")).toBe(false);
    expect(screens("/inventory/locations")).toBe(true);
    expect(screens("/inventory/locations/17")).toBe(true);
  });

  it("does not count a parent route whose required modules are all off", () => {
    vi.spyOn(moduleRegistry, "getRoutes").mockReturnValue([
      { path: "/tools", component: () => null, requiresModules: ["stats"] },
      { path: "/tools/:id", component: () => null },
    ]);
    expect(screensOf(["tools"], nav("/tools", ["/tools"]))("/tools")).toBe(
      false,
    );
    expect(
      screensOf(["tools", "stats"], nav("/tools", ["/tools"]))("/tools"),
    ).toBe(true);
  });
});
