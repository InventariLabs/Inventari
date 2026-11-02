import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import deCommon from "../locales/de/common.json";
import enCommon from "../locales/en/common.json";
import esCommon from "../locales/es/common.json";
import frCommon from "../locales/fr/common.json";
import plCommon from "../locales/pl/common.json";
import deItems from "../locales/de/items.json";
import enItems from "../locales/en/items.json";
import esItems from "../locales/es/items.json";
import frItems from "../locales/fr/items.json";
import plItems from "../locales/pl/items.json";

/**
 * Every unit the backend seeds (backend/app/seed_profiles/_uom_data.py) —
 * read from that module, not from a copy of it.
 *
 * `unitLabel` resolves a symbol through `common:units.<symbol>` and degrades
 * to the raw symbol when the catalogue has no entry — which makes a missing
 * key read exactly like a deliberate decision to keep the symbol, so nothing
 * flags the gap. This test is that flag: a unit added to the seed without a
 * dictionary entry fails here, in every language at once. The picker's side
 * is the same class one catalogue over: `items:uomNames.<name>`, keyed by
 * the seed's English name, falls back to that name when the key is missing —
 * a Polish workspace reading "Bag" among "Worek" and "Butelka".
 *
 * The symbol list used to be hand-copied into this file, which measured the
 * dictionary against its own copy of the catalogue: a unit planted in the
 * seed with no entry went green, and only a deleted label went red. The list
 * is read from the seed module now, and the planted unit is the measurement.
 * `items:uomNames.Cup (Metric)` is kept on purpose: the seed carries
 * "Cup (US)" only, and a workspace may still define a metric cup of its own.
 */
const SEED = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../../backend/app/seed_profiles/_uom_data.py",
);

/** The two seed lists (neutral base and US kitchen); the categories above them are not units. */
function seededUnits(text: string): { names: string[]; symbols: string[] } {
  const start = text.indexOf("UOM_UNITS:");
  if (start < 0) throw new Error(`no UOM_UNITS catalogue in ${SEED}`);
  const lists = text.slice(start);
  return {
    names: [...lists.matchAll(/'name': '([^']+)'/g)].map((m) => m[1]),
    symbols: [...lists.matchAll(/'symbol': '([^']+)'/g)].map((m) => m[1]),
  };
}

const { names, symbols } = seededUnits(readFileSync(SEED, "utf8"));

const catalogues: Array<
  [string, Record<string, unknown>, Record<string, unknown>]
> = [
  ["en", enCommon, enItems],
  ["pl", plCommon, plItems],
  ["de", deCommon, deItems],
  ["fr", frCommon, frItems],
  ["es", esCommon, esItems],
];

describe("the unit catalogue has a dictionary entry in every language", () => {
  it("reads both seed lists", () => {
    // an empty extraction would pass every loop below — the instrument must
    // fail loudly when the module outgrows its parser
    expect(symbols.length).toBeGreaterThan(0);
    expect(symbols.length).toBe(names.length);
  });

  it.each(catalogues)("names every seeded unit in %s", (_language, catalog) => {
    const units = catalog.units as Record<string, unknown> | undefined;
    expect(units).toBeDefined();
    for (const symbol of symbols) {
      expect(units?.[symbol], `units.${symbol}`).toBeTruthy();
    }
  });

  it.each(catalogues)(
    "names every seeded unit's name in %s",
    (_language, _catalog, items) => {
      const uomNames = items.uomNames as Record<string, unknown> | undefined;
      expect(uomNames).toBeDefined();
      for (const name of names) {
        expect(uomNames?.[name], `uomNames.${name}`).toBeTruthy();
      }
    },
  );
});
