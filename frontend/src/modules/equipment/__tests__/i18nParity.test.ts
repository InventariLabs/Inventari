import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { SUPPORTED_LANGUAGES } from "@/i18n/languages";
import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";

/**
 * Five-language i18n parity contract for the equipment module.
 *
 * A partial translation must not ship: every key
 * added to ``en.json`` (including nested children) must also appear in
 * ``pl``, ``de``, ``fr`` and ``es`` so the FE never falls back to English
 * during a localized session. The native ``react-i18next`` lookup would
 * silently substitute the English key, masking the gap. This test walks
 * every nested key in all five catalogs and asserts (a) flat keys, (b)
 * children keys, and (c) no empty / whitespace-only leaf values.
 *
 * The catalogs come from the module's own i18n directory rather than a
 * hand-kept import per language: a file added per the recipe lands here
 * with no list to extend, and the set of them is held to
 * `SUPPORTED_LANGUAGES` below: every maintained language has a catalog and
 * no catalog belongs to a language that is not shipped. A community language
 * may have no catalog or a partial one, so the contract below holds the
 * maintained ones.
 */

type Catalog = Record<string, unknown>;

const catalogModules = import.meta.glob<Catalog>("../i18n/*.json", {
  eager: true,
  import: "default",
});

const catalogs: Record<string, Catalog> = Object.fromEntries(
  Object.entries(catalogModules).map(([file, catalog]) => [
    file.match(/(\w+)\.json$/)![1],
    catalog,
  ]),
);

/** The catalogs a change must bring in full: a community language's catalog
 *  may be absent or behind, and is read in English per key. */
const maintainedCatalogs = Object.entries(catalogs).filter(([lang]) =>
  (MAINTAINED_LANGUAGES as string[]).includes(lang),
);

function collectKeys(node: unknown, prefix: string[] = []): string[] {
  if (node == null) return [];
  if (typeof node === "string") return [prefix.join(".")];
  if (Array.isArray(node)) {
    return node.flatMap((v, i) => collectKeys(v, [...prefix, String(i)]));
  }
  if (typeof node === "object") {
    return Object.entries(node as Catalog).flatMap(([k, v]) =>
      collectKeys(v, [...prefix, k]),
    );
  }
  return [];
}

function collectLeafStrings(node: unknown): string[] {
  if (node == null) return [];
  if (typeof node === "string") return [node];
  if (Array.isArray(node)) return node.flatMap(collectLeafStrings);
  if (typeof node === "object") {
    return Object.values(node as Catalog).flatMap(collectLeafStrings);
  }
  return [];
}

/** Collapse `key_one` / `key_few` / … onto `key` for cross-language compare. */
function collectFamilies(catalog: Catalog): string[] {
  const bases = new Set(
    collectKeys(catalog).map((key) => {
      const suffix = PLURAL_SUFFIXES.find((s) => key.endsWith(s));
      return suffix ? key.slice(0, -suffix.length) : key;
    }),
  );
  return [...bases].sort();
}

describe("equipment i18n parity", () => {
  it("catalogs are present for every maintained locale, and for none that is not shipped", () => {
    const present = Object.keys(catalogs);

    expect(present).toEqual(expect.arrayContaining([...MAINTAINED_LANGUAGES]));
    expect(SUPPORTED_LANGUAGES).toEqual(expect.arrayContaining(present));
  });

  it.each(maintainedCatalogs)(
    "%s exposes 35 top-level namespaces",
    (_lang, catalog) => {
      // `gettingStarted` moved to a top-level namespace so
      // GettingStarted resolves `equipment:gettingStarted.title`
      // (mirrors the warehouse module). added `settings` for the
      // module-settings schema keys. added `table` for the desktop
      // asset table; added `bulk_return` for the batch checkin.
      // `permissions` carries the labels the roles matrix renders for the
      // module's own keys, which is why it is a catalog namespace and not
      // shell copy.
      // removed `_vocabulary` — dev-only SSOT notes, not UI strings.
      expect(Object.keys(catalog).length).toBe(36);
    },
  );

  it("en/pl/de/fr/es expose the same top-level key set", () => {
    const enKeys = Object.keys(catalogs.en).sort();
    for (const [lang, catalog] of maintainedCatalogs) {
      if (lang === "en") continue;
      expect(Object.keys(catalog).sort(), `${lang} top-level keys`).toEqual(
        enKeys,
      );
    }
  });

  it.each(maintainedCatalogs)(
    "%s exposes the same nested key set as English",
    (_lang, catalog) => {
      // Plural families are compared by their base: Polish carries
      // one/few/many where English carries one/other, and demanding an
      // identical key list would force wrong forms into a language.
      expect(collectFamilies(catalog)).toEqual(collectFamilies(catalogs.en));
    },
  );

  it.each(maintainedCatalogs)(
    "%s has no empty / whitespace-only leaf values",
    (_lang, catalog) => {
      for (const leaf of collectLeafStrings(catalog)) {
        expect(leaf, "empty leaf value").toMatch(/\S/);
      }
    },
  );
});

/**
 * Key-usage scan (slice 1b): the parity tests above compare catalogs
 * against each other, so a key missing in ALL five locales passes
 * unnoticed — exactly what happened with `list.select_item`, which the
 * UI rendered as a raw key in the a11y tree. This scan extracts every
 * static ``t("...")`` literal from the module source and asserts the
 * key resolves in every catalog.
 *
 * Skipped on purpose:
 * - keys with an explicit namespace prefix (``common:actions.save``) —
 *   they belong to a different catalog,
 * - dynamic keys (template literals with ``${}``) — not statically
 *   resolvable,
 * - test files themselves.
 */

// Vitest runs with cwd = frontend root; jsdom rewrites import.meta.url,
// so resolve the module root from the process cwd instead.
const MODULE_ROOT = join(process.cwd(), "src/modules/equipment");

function collectSourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      return entry === "__tests__" ? [] : collectSourceFiles(full);
    }
    return /\.(ts|tsx)$/.test(entry) ? [full] : [];
  });
}

const T_CALL_RE = /\bt\(\s*["'`]([^"'`]+)["'`]/g;

export function collectUsedKeys(files: string[]): string[] {
  const keys = new Set<string>();
  for (const file of files) {
    const source = readFileSync(file, "utf8");
    for (const match of source.matchAll(T_CALL_RE)) {
      const key = match[1];
      if (key.includes(":")) continue; // explicit other namespace
      if (key.includes("${")) continue; // dynamic template key
      keys.add(key);
    }
  }
  return [...keys].sort();
}

/**
 * i18next plural families: a `t(key, { count })` call is satisfied by
 * `key_one` / `key_few` / `key_many` / `key_other` rather than `key`
 * itself, so both the parity walk and the usage scan must accept them.
 */
const PLURAL_SUFFIXES = ["_one", "_few", "_many", "_other", "_two", "_zero"];

function resolve(catalog: Catalog, key: string): unknown {
  let node: unknown = catalog;
  for (const segment of key.split(".")) {
    if (node == null || typeof node !== "object" || Array.isArray(node)) {
      return undefined;
    }
    node = (node as Catalog)[segment];
  }
  return node;
}

function keyExists(catalog: Catalog, key: string): boolean {
  if (typeof resolve(catalog, key) === "string") return true;
  return PLURAL_SUFFIXES.some(
    (suffix) => typeof resolve(catalog, key + suffix) === "string",
  );
}

export function findMissingKeys(catalog: Catalog, keys: string[]): string[] {
  return keys.filter((key) => !keyExists(catalog, key));
}

describe("equipment i18n key usage scan (slice 1b)", () => {
  it("resolver flags a synthetic missing key", () => {
    expect(findMissingKeys(catalogs.en, ["definitely.not.a.real.key"])).toEqual(
      ["definitely.not.a.real.key"],
    );
  });

  it.each(maintainedCatalogs)(
    "every static t() key used in module code exists in %s catalog",
    (_lang, catalog) => {
      const usedKeys = collectUsedKeys(collectSourceFiles(MODULE_ROOT));
      expect(usedKeys.length).toBeGreaterThan(0);
      expect(findMissingKeys(catalog, usedKeys)).toEqual([]);
    },
  );
});
