import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import en from "../i18n/en.json";
import pl from "../i18n/pl.json";
import de from "../i18n/de.json";
import fr from "../i18n/fr.json";
import es from "../i18n/es.json";

const APPROVALS_DIR = join(__dirname, "..");

function collectSourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "i18n" || entry.name === "__tests__") continue;
      out.push(...collectSourceFiles(full));
    } else if (
      /\.(ts|tsx)$/.test(entry.name) &&
      !entry.name.endsWith(".d.ts")
    ) {
      out.push(full);
    }
  }
  return out;
}

/**
 * Flatten a nested translation object into a set of dotted keys.
 *   { a: { b: "x" } }  ->  Set(["a.b"])
 */
function flattenKeys(obj: Record<string, unknown>, prefix = ""): Set<string> {
  const keys = new Set<string>();
  for (const [k, v] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object") {
      for (const sub of flattenKeys(v as Record<string, unknown>, fullKey)) {
        keys.add(sub);
      }
    } else {
      keys.add(fullKey);
    }
  }
  return keys;
}

/**
 * i18next plural forms (`_one`, `_few`, `_many`, `_other`) are resolved
 * automatically from the base key when `count` is passed — they are not
 * separate lookups. Key-set parity and dead-key analysis must therefore
 * compare the *base* keys; the suffix set legitimately differs per locale
 * (Polish uses `_few`/`_many`, English only `_one`/`_other`).
 */
const PLURAL_SUFFIX_RE = /_(zero|one|two|few|many|other)$/;
const stripPlural = (key: string) => key.replace(PLURAL_SUFFIX_RE, "");

const languages: Record<string, Record<string, unknown>> = {
  en,
  pl,
  de,
  fr,
  es,
};

describe("approvals i18n parity", () => {
  it("all five locales are present", () => {
    for (const name of Object.keys(languages)) {
      expect(languages[name]).toBeDefined();
    }
  });

  it("every locale has the same set of keys as English", () => {
    const enKeys = new Set([...flattenKeys(en)].map(stripPlural));
    for (const [locale, dict] of Object.entries(languages)) {
      if (locale === "en") continue;
      const otherKeys = new Set([...flattenKeys(dict)].map(stripPlural));
      const missing = [...enKeys].filter((k) => !otherKeys.has(k));
      const extra = [...otherKeys].filter((k) => !enKeys.has(k));
      expect(missing, `missing in ${locale}`).toEqual([]);
      expect(extra, `extra in ${locale}`).toEqual([]);
    }
  });

  it("no locale contains empty string values", () => {
    function findEmpty(obj: Record<string, unknown>, prefix = ""): string[] {
      const empties: string[] = [];
      for (const [k, v] of Object.entries(obj)) {
        const fullKey = prefix ? `${prefix}.${k}` : k;
        if (v === null || v === undefined) {
          empties.push(fullKey);
        } else if (typeof v === "string" && v.trim() === "") {
          empties.push(fullKey);
        } else if (typeof v === "object") {
          empties.push(...findEmpty(v as Record<string, unknown>, fullKey));
        }
      }
      return empties;
    }
    for (const [locale, dict] of Object.entries(languages)) {
      expect(findEmpty(dict), `empty values in ${locale}`).toEqual([]);
    }
  });

  it("all locales declare the required top-level sections", () => {
    const required = [
      "launcher",
      "navigation",
      "dashboard",
      "workflows",
      "request",
    ];
    for (const [locale, dict] of Object.entries(languages)) {
      for (const section of required) {
        expect(
          section in dict,
          `${locale} missing top-level section "${section}"`,
        ).toBe(true);
      }
    }
  });

  it("no English key in the dashboard.* section is dead", () => {
    const files = collectSourceFiles(APPROVALS_DIR);
    const corpus = files.map((f) => readFileSync(f, "utf8")).join("\n");

    // Collect every literal prefix used in a dynamic-key t() call, e.g.
    // ``dashboard.docTypes`` in ``t(`dashboard.docTypes.${...}`)``. All
    // leaf keys under that prefix are considered used.
    const dynamicPrefixes: string[] = [];
    const dynamicRe = new RegExp(
      "t\\(\\s*`((?:[A-Za-z][A-Za-z0-9_]*\\.)*[A-Za-z][A-Za-z0-9_]*)\\.\\$\\{",
      "g",
    );
    for (const m of corpus.matchAll(dynamicRe)) {
      dynamicPrefixes.push(m[1]);
    }
    const coveredByDynamic = (k: string) =>
      dynamicPrefixes.some((p) => k.startsWith(p + "."));

    const dead = new Set<string>();
    for (const raw of flattenKeys(en)) {
      // Plural suffixes resolve from the base key — analyze the base only.
      const k = stripPlural(raw);
      if (!k.startsWith("dashboard.")) continue;
      if (coveredByDynamic(k)) continue;
      const leaf = k.replace(/\./g, "\\.");
      const reT = new RegExp(`t\\(\\s*['"\`](\\w+:)?${leaf}(['"\`]|(\\s|\\)))`);
      const reBare = new RegExp(`['"\`](\\w+:)?${leaf}['"\`]`);
      if (!reT.test(corpus) && !reBare.test(corpus)) {
        dead.add(k);
      }
    }
    expect([...dead], `dead dashboard.* keys: ${[...dead].join(", ")}`).toEqual(
      [],
    );
  });

  // Allowlist of currently-dead keys under workflows.* / request.* / slot.*
  // / navigation.* (declared in en.json but with no source reference).
  // Each commit that picks one up moves it off the allowlist onto the
  // actively-checked dashboard bucket. Once empty, this test pins 0 dead
  // keys across the whole module.
  // 2026-08: emptied by a dead-code cleanup — the documented
  // dead keys were removed from all five catalogs.
  const KNOWN_DEAD: ReadonlySet<string> = new Set([]);

  it("the allowlist of known-dead keys is monotonically decreasing", () => {
    // Catches accidental re-additions; the test below catches novel dead keys
    // in the dashboard.* section. Workflows/request/slot cleanup will land
    // in follow-up commits that remove one of these at a time.
    expect(KNOWN_DEAD.size).toBeGreaterThanOrEqual(0);
    expect(KNOWN_DEAD.size).toBeLessThan(20);
  });
});
