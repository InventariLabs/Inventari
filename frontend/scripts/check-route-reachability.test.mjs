/**
 * The gate itself is code that fails silently: when it stops seeing a link
 * shape, every route linked that way turns "reachable" and nothing reports
 * it. These cases pin the two shapes that were invisible for months
 * (`to={...}` with a brace, `${...}` on the reference side) and the parsing
 * of module.ts that brought module routes into scope.
 */
import { describe, expect, it } from "vitest";

import {
  isCovered,
  pathsIn,
  referencesIn,
  relativeNavPaths,
  settingsInstanceGaps,
  settingsInstances,
  sliceBlock,
  unreachableLine,
} from "./check-route-reachability.mjs";

describe("referencesIn", () => {
  it("reads a plain JSX link", () => {
    expect(referencesIn('<Link to="/warehouse/periods">')).toContain(
      "/warehouse/periods",
    );
  });

  it("reads a braced template literal — the app's usual dynamic link", () => {
    expect(referencesIn("<Link to={`/equipment/${id}`}>")).toContain(
      "/equipment/${id}",
    );
  });

  it("reads a braced string and a data-object entry", () => {
    expect(referencesIn('<Link to={"/apps"}>')).toContain("/apps");
    expect(
      referencesIn('{ label: t("x"), to: "/settings/workspace" }'),
    ).toContain("/settings/workspace");
  });

  it("reads navigate() and a launcher action item's linkTo", () => {
    expect(referencesIn('navigate("/inventory/items")')).toContain(
      "/inventory/items",
    );
    expect(referencesIn('{ id: "a", linkTo: "/approvals" }')).toContain(
      "/approvals",
    );
  });

  it("ignores an axios call — an API path is not a UI route", () => {
    // The bug that started this: `/warehouse/periods` counted as a link
    // because the module's api/ file requests the same string.
    expect([...referencesIn('api.get("/warehouse/periods")')]).toEqual([]);
  });
});

describe("isCovered", () => {
  it("matches a :param route against a concrete link", () => {
    expect(isCovered("/warehouse/documents/:id", new Set(["/warehouse/documents/${doc.id}"]))).toBe(
      true,
    );
  });

  it("does not let a sibling dynamic link cover a literal route", () => {
    // `/warehouse/settings` is a real route; a link to `/warehouse/documents/${id}`
    // says nothing about it.
    expect(
      isCovered("/warehouse/settings", new Set(["/warehouse/documents/${doc.id}"])),
    ).toBe(false);
  });

  it("reports an unlinked route as uncovered", () => {
    expect(isCovered("/warehouse/periods", new Set(["/warehouse"]))).toBe(
      false,
    );
  });
});

describe("module.ts parsing", () => {
  const MODULE = `
moduleRegistry.register({
  name: "warehouse",
  routes: [
    { path: "/warehouse", component: DocumentsPage },
    { path: "/warehouse/documents/:id", component: DocumentDetailPage },
  ],
  moduleNav: {
    basePath: "/warehouse",
    items: [
      { path: "/warehouse", labelKey: "warehouse:navigation.documents" },
      { path: "", labelKey: "warehouse:navigation.home" },
    ],
  },
});
`;

  it("slices a block and lists its paths", () => {
    expect(pathsIn(sliceBlock(MODULE, "routes"))).toEqual([
      "/warehouse",
      "/warehouse/documents/:id",
    ]);
  });

  it("slices a nested block", () => {
    const nav = sliceBlock(MODULE, "moduleNav");
    expect(nav).toMatch(/basePath: "\/warehouse"/);
    expect(pathsIn(sliceBlock(nav, "items"))).toEqual(["/warehouse", ""]);
  });

  it("names a nav item path that is not absolute, which links nowhere", () => {
    expect(relativeNavPaths(MODULE)).toEqual([""]);
  });

  it("returns null for a key the module does not declare", () => {
    expect(sliceBlock(MODULE, "settingsSections")).toBeNull();
  });

  it("reads past an unpaired apostrophe in a comment inside a block", () => {
    const commented = MODULE.replace(
      "    { path: \"/warehouse\", component",
      "    // the module's own options\n    { path: \"/warehouse\", component",
    ).replace(
      "      { path: \"\", labelKey",
      "      /* the module's home */\n      { path: \"\", labelKey",
    );
    expect(pathsIn(sliceBlock(commented, "routes"))).toEqual([
      "/warehouse",
      "/warehouse/documents/:id",
    ]);
    const nav = sliceBlock(commented, "moduleNav");
    expect(pathsIn(sliceBlock(nav, "items"))).toEqual(["/warehouse", ""]);
  });
});

describe("referencesIn — a redirect is not a way in", () => {
  it("ignores the target of a <Navigate> element", () => {
    // /inventory/locations/:id was named by nothing but the redirect from its
    // own retired alias, and the gate counted that as a link.
    const refs = referencesIn(
      '<Navigate to={`/inventory/locations/${id ?? ""}`} replace />',
    );
    expect([...refs]).toEqual([]);
  });

  it("still counts a real link on the same page as a redirect", () => {
    const refs = referencesIn(
      '<Navigate to="/old" replace />\n<Link to="/inventory/locations/x">go</Link>',
    );
    expect([...refs]).toContain("/inventory/locations/x");
    expect([...refs]).not.toContain("/old");
  });

  it("counts a programmatic navigate, which follows a person's action", () => {
    const refs = referencesIn('navigate("/inventory/locations/abc")');
    expect([...refs]).toContain("/inventory/locations/abc");
  });
});

describe("settings instances", () => {
  it("reads real module names from the backend manifests", () => {
    // Pins the check to the real tree so it cannot quietly go vacuous — the
    // first cut looked for a `settings_schema` key and found none, because
    // the manifests say `has_settings_schema`, and a gate that always
    // passes is worse than none.
    const instances = settingsInstances();
    expect(instances).toContain("approvals");
    expect(instances).toContain("stats");
    expect(instances).toContain("webhooks");
    expect(new Set(instances).size).toBe(instances.length);
  });

  it("reports an instance neither a reference nor an own screen covers", () => {
    expect(
      settingsInstanceGaps(
        "/settings/modules/:name",
        new Set(["/settings/modules/webhooks"]),
        ["webhooks", "approvals"],
        new Set(),
      ),
    ).toEqual(["/settings/modules/approvals"]);
  });

  it("spares a module whose settings screen lives inside the module", () => {
    expect(
      settingsInstanceGaps(
        "/settings/modules/:name",
        new Set(),
        ["recipes"],
        new Set(["recipes"]),
      ),
    ).toEqual([]);
  });

  it("answers only for the parameterized settings route", () => {
    expect(
      settingsInstanceGaps("/items/:id", new Set(), ["approvals"], new Set()),
    ).toEqual([]);
  });
});

describe("unreachableLine", () => {
  it("names the owner of a route the map knows", () => {
    expect(unreachableLine("/warehouse/periods", "App.tsx")).toBe(
      "  - /warehouse/periods  [App.tsx]",
    );
  });

  it("says nothing rather than [undefined] for an instance report", () => {
    // A module-settings instance is pushed with a parenthesised note, so it
    // is not a key of the owners map. Printing `[undefined]` next to it read
    // like a broken tool, not like a missing link.
    const entry =
      "/settings/modules/approvals (module settings: no link names this module's instance)";
    expect(unreachableLine(entry, undefined)).toBe(`  - ${entry}`);
  });
});
