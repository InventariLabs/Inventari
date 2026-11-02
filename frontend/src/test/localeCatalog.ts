import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * Reading the locale directory as data.
 *
 * The parity gate used to import twenty locale files by hand and hold a
 * five-language list in a constant: a directory added per the recipe was
 * invisible to it — green while measuring nothing. Every question the gates
 * ask now starts here: which languages exist (directories under locales/),
 * which namespaces a language carries, and how much of the English catalog
 * a language actually holds. Pure path-in, data-out, so the unit tests can
 * exercise them on fixture directories instead of the real tree.
 */

export type Catalog = Record<string, unknown>;

/** Languages found in the locales directory, sorted — the directory, not a
 *  list in code, is what the gates treat as the set of shipped languages. */
export function listLanguages(localesDir: string): string[] {
  if (!existsSync(localesDir)) return [];
  return readdirSync(localesDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

/** Namespace names (`.json` files) a language's directory carries, sorted. */
export function listNamespaces(localesDir: string, language: string): string[] {
  const dir = join(localesDir, language);
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((name) => name.endsWith(".json"))
    .map((name) => name.replace(/\.json$/, ""))
    .sort();
}

/** Parses a catalog file; null when the file is absent or not valid JSON —
 *  a broken file is the gate's finding, not a crash. */
export function readCatalog(path: string): Catalog | null {
  if (!existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, "utf-8")) as Catalog;
  } catch {
    return null;
  }
}

/** Every string leaf of a catalog with its dotted path. An empty string is
 *  a leaf too — presence is decided later, emptiness means untranslated. */
export function flatLeafValues(
  node: unknown,
  prefix: string[] = [],
  out: Map<string, string> = new Map(),
): Map<string, string> {
  if (node == null) return out;
  if (typeof node === "string") {
    out.set(prefix.join("."), node);
  } else if (Array.isArray(node)) {
    node.forEach((value, index) =>
      flatLeafValues(value, [...prefix, String(index)], out),
    );
  } else if (typeof node === "object") {
    for (const [key, value] of Object.entries(node as Catalog)) {
      flatLeafValues(value, [...prefix, key], out);
    }
  }
  return out;
}

/** The English catalog's key set — the denominator of every coverage number.
 *  Keys are `namespace:path`, i18next's own identity: twenty-five key names
 *  exist in more than one core namespace, and without the namespace a value
 *  in `common` would count as answering a key missing from `labels` — the
 *  gate green over a key the reader sees as raw text. */
export function enKeySet(localesDir: string, namespaces: string[]): string[] {
  const keys: string[] = [];
  for (const namespace of namespaces) {
    const catalog = readCatalog(join(localesDir, "en", `${namespace}.json`));
    if (catalog) {
      for (const path of flatLeafValues(catalog).keys()) {
        keys.push(`${namespace}:${path}`);
      }
    }
  }
  return keys.sort();
}

export interface LanguageCoverage {
  /** Keys of en the language holds with a non-empty value. */
  present: number;
  /** Keys of en, total. */
  total: number;
  /** present/total as a percent, floored to one decimal. */
  percent: number;
  /** en keys (`namespace:path`) missing or empty in the language, sorted. */
  missing: string[];
  /** keys (`namespace:path`) the language carries that en does not, sorted. */
  extra: string[];
}

/** Coverage of one language against en over the given namespaces. */
export function coverageOf(
  localesDir: string,
  language: string,
  namespaces: string[],
  enKeys: string[],
): LanguageCoverage {
  const enSet = new Set(enKeys);
  const values = new Map<string, string>();
  for (const namespace of namespaces) {
    const catalog = readCatalog(
      join(localesDir, language, `${namespace}.json`),
    );
    if (catalog) {
      for (const [path, value] of flatLeafValues(catalog)) {
        values.set(`${namespace}:${path}`, value);
      }
    }
  }
  const present: string[] = [];
  const missing: string[] = [];
  for (const key of enKeys) {
    const value = values.get(key);
    if (value !== undefined && value.trim() !== "") {
      present.push(key);
    } else {
      missing.push(key);
    }
  }
  const extra = [...values.keys()].filter((key) => !enSet.has(key)).sort();
  const percent =
    enKeys.length === 0
      ? 100
      : Math.floor((present.length / enKeys.length) * 1000) / 10;
  return {
    present: present.length,
    total: enKeys.length,
    percent,
    missing,
    extra,
  };
}

/** What a community language declared: the share of the interface it held
 *  and how many keys that was. The share is what the menu shows; the key
 *  count is what the gate holds, because the share shrinks every time
 *  English grows and a community language is not asked to follow. */
export interface CommunityDeclaration {
  percent: number;
  keys: number;
}

/** One entry per shipped language except en: a percent for a maintained
 *  language, a {@link CommunityDeclaration} for a community one. */
export type CoverageDeclaration = Record<string, number | CommunityDeclaration>;

/** The declared coverage — the baseline the gate holds languages to. `en`
 *  is the source and is never listed; every other shipped language needs a
 *  declaration, because a language without one is exactly the measurement
 *  the gate refuses to fake. */
export function readCoverageDeclaration(
  path: string,
): CoverageDeclaration | null {
  if (!existsSync(path)) return null;
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, "utf-8"));
    if (
      parsed === null ||
      typeof parsed !== "object" ||
      Array.isArray(parsed)
    ) {
      return null;
    }
    return parsed as CoverageDeclaration;
  } catch {
    return null;
  }
}

/**
 * What a language's coverage obliges, as findings — empty when the gate is
 * satisfied.
 *
 * A maintained language is held to every English key, whatever the
 * declaration file carries: a change adds its strings to all of them, and a
 * baseline cannot excuse a gap there. A community language is held only to
 * the number of keys it declared, so a change that adds a string in English
 * alone leaves it green until the language catches up; losing a translation
 * it held is a regression, and the finding says by how many.
 */
export function coverageFindings(
  coverage: LanguageCoverage,
  options: { community: boolean; declaredKeys: number },
): string[] {
  if (!options.community) {
    return coverage.missing.map((key) => `missing ${key}`);
  }
  return coverage.present < options.declaredKeys
    ? [
        `holds ${coverage.present} keys, below the ${options.declaredKeys} it declared`,
      ]
    : [];
}
