/**
 * The gate itself is code that fails silently: when it stops seeing the
 * `standalone` block, every focus module vanishes from the report and nothing
 * is ever unaccounted again. These cases pin the declaration parsing
 * (including the comment styles that broke the first version of the brace
 * counter), the longest-prefix-first classification, and the baseline
 * semantics that let --baseline fail only on NEW findings.
 */
import { describe, expect, it } from "vitest";

import {
  buildPrefixTable,
  classifyRoute,
  collectFindings,
  diffBaseline,
  findingKey,
  matchPrefix,
  parseCoreSectionPrefixes,
  parseStandalone,
  sliceBlock,
  sliceConst,
} from "./check-focus-reachability.mjs";

// Mirrors CORE_SECTION_PATH_PREFIXES in src/lib/moduleRegistry/coreSections.ts.
const SECTION_PREFIXES = {
  labels: ["/inventory/labels"],
  scan: ["/inventory/scan", "/labels/scan"],
  stats: ["/inventory/stats"],
  stock_takes: ["/inventory/stock-takes"],
  archive: ["/inventory/items/archived", "/inventory/locations/archived"],
};
const TABLE = buildPrefixTable(SECTION_PREFIXES);

// The smallest scope that exercises every classification: one route per
// adoptable section, the keepable lists, the base, and an extra screen.
const SCOPE = [
  { path: "/inventory", owner: "inventory", isBase: true },
  { path: "/inventory/items", owner: "inventory" },
  { path: "/inventory/items/:id", owner: "inventory" },
  { path: "/inventory/locations", owner: "inventory" },
  { path: "/inventory/locations/archived", owner: "inventory" },
  { path: "/inventory/stock", owner: "inventory" },
  { path: "/inventory/lots", owner: "inventory" },
  { path: "/inventory/stock-takes", owner: "inventory" },
  { path: "/inventory/moves", owner: "inventory" },
  { path: "/inventory/categories", owner: "inventory" },
  { path: "/inventory/labels", owner: "inventory" },
  { path: "/inventory/scan", owner: "inventory" },
  { path: "/inventory/stats", owner: "inventory" },
  { path: "/inventory/items/archived", owner: "inventory" },
  { path: "/labels/scan/:code", owner: "printing" },
];

const EQUIPMENT = {
  name: "equipment",
  coreSections: {
    labels: "adopt",
    scan: "adopt",
    stats: "renounce",
    stock_takes: "renounce",
    archive: "renounce",
  },
  keepCoreNav: [],
};

describe("parseCoreSectionPrefixes", () => {
  it("reads the map past its type annotation and documentary comments", () => {
    // Both hazards are real: `string[]` in the annotation is the first `[`
    // after the name, and the entries carry `//` comments with lone
    // backticks/apostrophes that read as string openers to a naive scanner.
    const text = `
export const CORE_SECTION_PATH_PREFIXES: Record<
  AdoptableCoreSection,
  string[]
> = {
  labels: ["/inventory/labels"],
  // \`/labels/scan/:code\` is printing's flat route.
  scan: ["/inventory/scan", "/labels/scan"],
  stats: ["/inventory/stats"],
};
`;
    expect(parseCoreSectionPrefixes(text)).toEqual({
      labels: ["/inventory/labels"],
      scan: ["/inventory/scan", "/labels/scan"],
      stats: ["/inventory/stats"],
    });
  });
});

describe("parseStandalone", () => {
  const MODULE = `
moduleRegistry.register({
  name: "equipment",
  standalone: {
    coreSections: {
      labels: "adopt",
      scan: "adopt",
      stats: "renounce",
      stock_takes: "renounce",
      archive: "renounce",
    },
    keepCoreNav: ["items"],
  },
});
`;

  it("reads the declaration", () => {
    expect(parseStandalone(MODULE)).toEqual({
      coreSections: {
        labels: "adopt",
        scan: "adopt",
        stats: "renounce",
        stock_takes: "renounce",
        archive: "renounce",
      },
      keepCoreNav: ["items"],
    });
  });

  it("returns null for a module that does not stand alone", () => {
    expect(
      parseStandalone('moduleRegistry.register({ name: "recipes" })'),
    ).toBeNull();
  });

  it("reads an empty keepCoreNav as the declared choice it is", () => {
    expect(
      parseStandalone(MODULE.replace('["items"]', "[]")).keepCoreNav,
    ).toEqual([]);
  });
});

describe("matchPrefix", () => {
  it("prefers the longest prefix — stock-takes is not stock", () => {
    expect(matchPrefix("/inventory/stock-takes", TABLE)).toMatchObject({
      kind: "section",
      section: "stock_takes",
    });
    expect(matchPrefix("/inventory/stock", TABLE)).toMatchObject({
      kind: "coreNav",
      section: "stock",
    });
  });

  it("matches on a segment boundary only", () => {
    // `/inventory/stock` must not swallow a hypothetical /inventory/stockade.
    expect(matchPrefix("/inventory/stockade", TABLE)).toBeNull();
    expect(matchPrefix("/inventory/stock/as-of", TABLE)).toMatchObject({
      section: "stock",
    });
  });

  it("covers a parameterized route below the prefix", () => {
    expect(matchPrefix("/labels/scan/:code", TABLE)).toMatchObject({
      kind: "section",
      section: "scan",
    });
  });
});

describe("classifyRoute", () => {
  it("classifies adopted, renounced, kept and core-list routes", () => {
    const ctx = { basePath: "/inventory", focus: EQUIPMENT, table: TABLE };
    expect(classifyRoute("/inventory/labels", ctx).status).toBe("adopted");
    expect(classifyRoute("/labels/scan/:code", ctx).status).toBe("adopted");
    expect(classifyRoute("/inventory/stats", ctx).status).toBe("renounced");
    expect(classifyRoute("/inventory/items", ctx).status).toBe("core-list");
    expect(classifyRoute("/inventory", ctx).status).toBe("base");
    const kept = { ...ctx, focus: { ...EQUIPMENT, keepCoreNav: ["items"] } };
    expect(classifyRoute("/inventory/items", kept).status).toBe("kept");
  });

  it("treats a section missing from the declaration as unaccounted", () => {
    const hole = {
      ...EQUIPMENT,
      coreSections: { ...EQUIPMENT.coreSections, labels: undefined },
    };
    delete hole.coreSections.labels;
    const ctx = { basePath: "/inventory", focus: hole, table: TABLE };
    expect(classifyRoute("/inventory/labels", ctx).status).toBe("unaccounted");
  });
});

describe("collectFindings", () => {
  it("accounts for every route under a complete declaration", () => {
    const { findings, perModule } = collectFindings(SCOPE, [EQUIPMENT], TABLE);
    expect(findings).toEqual([]);
    expect(perModule.get("equipment")).toMatchObject({
      adopted: 3,
      renounced: 4,
      "core-list": 7,
      base: 1,
    });
  });

  it("names the orphaning owner and the focus module that dropped the route", () => {
    const hole = {
      ...EQUIPMENT,
      coreSections: { scan: "adopt", stats: "renounce" },
    };
    const { findings } = collectFindings(SCOPE, [hole], TABLE);
    const keys = findings.map(findingKey);
    // labels is undeclared → the pool route is orphaned by inventory's hiding.
    expect(keys).toContain(
      "/inventory/labels  [owner: inventory, focus: equipment]",
    );
    // /labels/scan/:code sits under the adopted scan section — accounted.
    expect(keys).not.toContain(
      "/labels/scan/:code  [owner: printing, focus: equipment]",
    );
  });

  it("reports a prefix no mounted route matches as map drift", () => {
    const drifted = buildPrefixTable({
      ...SECTION_PREFIXES,
      labels: ["/inventory/labels", "/inventory/label-deleted"],
    });
    const { findings } = collectFindings(SCOPE, [EQUIPMENT], drifted);
    expect(findings.map(findingKey)).toContain(
      'map drift: "/inventory/label-deleted" (section: labels) matches no mounted route',
    );
  });
});

describe("diffBaseline", () => {
  const hole = {
    ...EQUIPMENT,
    coreSections: { scan: "adopt", stats: "renounce" },
  };
  const { findings } = collectFindings(SCOPE, [hole], TABLE);

  it("passes with findings that are in the baseline", () => {
    const { newFindings, fixed } = diffBaseline(
      findings,
      findings.map(findingKey),
    );
    expect(newFindings).toEqual([]);
    expect(fixed).toEqual([]);
  });

  it("fails on a finding the baseline does not know", () => {
    const { newFindings, fixed } = diffBaseline(findings, []);
    expect(newFindings.length).toBe(findings.length);
    expect(fixed).toEqual([]);
  });

  it("reports baseline entries that no longer occur as fixed", () => {
    const { newFindings, fixed } = diffBaseline([], [findingKey(findings[0])]);
    expect(newFindings).toEqual([]);
    expect(fixed).toEqual([findingKey(findings[0])]);
  });
});

describe("sliceConst / sliceBlock", () => {
  it("returns null for a name the file does not declare", () => {
    expect(sliceConst("const x = 1;", "CORE_SECTION_PATH_PREFIXES")).toBeNull();
    expect(sliceBlock("const x = 1;", "standalone")).toBeNull();
  });
});
