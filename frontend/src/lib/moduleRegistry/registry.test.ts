import { afterEach, describe, expect, it, vi } from "vitest";
import { Home } from "lucide-react";
import { moduleRegistry } from "./registry";
import { applyNavOverrides } from "./registryQueries";
import type {
  ColumnContributor,
  ListFilterContributor,
  ModuleNavItem,
} from "./moduleInterfaces";

// The registry is a module-level singleton and keeps the first registration
// of a name it has seen, so every test registers under a name of its own.
let counter = 0;
const unique = (prefix: string) => `${prefix}_reg_${counter++}`;

const Page = () => null;

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ModuleRegistry.warnOrphanedNav", () => {
  it("accepts a nav item whose route has a :param, without warning", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    const name = unique("paramnav");
    moduleRegistry.register({
      name,
      routes: [{ path: "/things/:id", component: Page }],
      moduleNav: {
        basePath: "/things",
        items: [{ path: "42", labelKey: "x", icon: Home }],
      },
    });
    moduleRegistry.warnOrphanedNav([name]);

    expect(warn).not.toHaveBeenCalled();
  });

  it("warns about a nav item that points at no route, even next to param routes", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const name = unique("orphannav");

    moduleRegistry.register({
      name,
      routes: [{ path: "/things/:id", component: Page }],
      moduleNav: {
        basePath: "/things",
        // Two segments against a one-segment pattern: not the same route.
        items: [{ path: "42/extra", labelKey: "x", icon: Home }],
      },
    });
    moduleRegistry.warnOrphanedNav([name]);

    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain(name);
    expect(String(warn.mock.calls[0][0])).toContain("/things/42/extra");
  });

  it("stays quiet about a nav item that is hidden because the module it needs is off", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const name = unique("gatednav");

    moduleRegistry.register({
      name,
      routes: [{ path: "/things", component: Page }],
      moduleNav: {
        basePath: "/things",
        // The guest module that hosts this screen is not registered: the
        // nav item is not shown, so a missing route is no defect.
        items: [
          {
            path: "/things/guest",
            labelKey: "x",
            icon: Home,
            requiresModules: [unique("absentguest")],
          },
        ],
      },
    });
    moduleRegistry.warnOrphanedNav([name]);

    expect(warn).not.toHaveBeenCalled();
  });

  it("warns again once the module a nav item needs is on but supplies no route", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const name = unique("gatednav");
    const guest = unique("guestnav");

    moduleRegistry.register({
      name,
      routes: [{ path: "/things", component: Page }],
      moduleNav: {
        basePath: "/things",
        items: [
          {
            path: "/things/guest",
            labelKey: "x",
            icon: Home,
            requiresModules: [guest],
          },
        ],
      },
    });
    moduleRegistry.register({ name: guest, routes: [] });
    moduleRegistry.warnOrphanedNav([name, guest]);

    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain("/things/guest");
  });
});

describe("ModuleRegistry contributors", () => {
  const filterOf = (
    key: string,
    requiredModule: string,
  ): ListFilterContributor => ({
    key,
    label: key,
    requiredModule,
    queryKey: [key],
    fetchTemplateIds: async () => [],
  });
  const columnOf = (
    key: string,
    requiredModule: string,
  ): ColumnContributor => ({
    key,
    label: key,
    requiredModule,
    render: () => null,
  });

  it("offers a module's list filters only while that module is enabled", () => {
    const name = unique("filtermod");
    moduleRegistry.register({
      name,
      routes: [],
      listFilterContributors: [filterOf(`${name}_chip`, name)],
    });

    expect(
      moduleRegistry
        .getListFilterContributors("items", [name])
        .map((c) => c.key),
    ).toContain(`${name}_chip`);
    expect(
      moduleRegistry.getListFilterContributors("items", []).map((c) => c.key),
    ).not.toContain(`${name}_chip`);
  });

  it("replaces a filter or column registered again under the same key", () => {
    const name = unique("rereg");
    const registerWith = (label: string) =>
      moduleRegistry.register({
        name,
        routes: [],
        listFilterContributors: [{ ...filterOf(`${name}_chip`, name), label }],
        columnContributors: [{ ...columnOf(`${name}_col`, name), label }],
      });
    registerWith("first");
    registerWith("second");

    const filters = moduleRegistry
      .getListFilterContributors("items", [name])
      .filter((c) => c.key === `${name}_chip`);
    const columns = moduleRegistry
      .getColumnContributors("items", [name])
      .filter((c) => c.key === `${name}_col`);

    expect(filters).toHaveLength(1);
    expect(filters[0].label).toBe("second");
    expect(columns).toHaveLength(1);
    expect(columns[0].label).toBe("second");
  });
});

describe("ModuleRegistry.warnUnmatchedNavOverrides", () => {
  it("names an override whose target is no navigation item", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const host = unique("navhost");
    const overrider = unique("navoverrider");
    moduleRegistry.register({
      name: host,
      routes: [{ path: `/${host}`, component: Page }],
      moduleNav: {
        basePath: `/${host}`,
        items: [{ path: `/${host}`, labelKey: "nav.host", icon: Home }],
      },
    });
    moduleRegistry.register({
      name: overrider,
      routes: [],
      navOverrides: [
        { targetPath: `/${host}`, hidden: true },
        { targetPath: "/inventory/labels", labelKey: "nav.codes" },
        { targetPath: "/inventory/lokations", hidden: true },
      ],
    });

    moduleRegistry.warnUnmatchedNavOverrides([overrider]);

    expect(warn).toHaveBeenCalledTimes(1);
    const said = String(warn.mock.calls[0][0]);
    expect(said).toContain(`"${overrider}"`);
    expect(said).toContain("/inventory/lokations");
    expect(said).not.toContain(`/${host}`);
    expect(said).not.toContain("/inventory/labels");
  });

  it("stays quiet for a module whose overrides all match", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const overrider = unique("navquiet");
    moduleRegistry.register({
      name: overrider,
      routes: [],
      navOverrides: [{ targetPath: "/inventory/scan", hidden: true }],
    });

    moduleRegistry.warnUnmatchedNavOverrides([overrider]);

    expect(warn).not.toHaveBeenCalled();
  });
});

describe("applyNavOverrides", () => {
  const items: ModuleNavItem[] = [
    { path: "/a", labelKey: "nav.a", icon: Home },
    { path: "/b", labelKey: "nav.b", icon: Home },
    { path: "/c", labelKey: "nav.c", icon: Home },
  ];

  it("returns the items untouched when no module overrides anything", () => {
    expect(applyNavOverrides(items, [])).toBe(items);
  });

  it("drops a hidden item and relabels another, leaving the rest alone", () => {
    const result = applyNavOverrides(items, [
      { targetPath: "/a", hidden: true },
      { targetPath: "/b", labelKey: "nav.renamed" },
    ]);

    expect(result.map((i) => i.path)).toEqual(["/b", "/c"]);
    expect(result[0].labelKey).toBe("nav.renamed");
    expect(result[1]).toBe(items[2]);
  });
});
