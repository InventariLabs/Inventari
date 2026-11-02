import { describe, expect, it } from "vitest";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";

/**
 * Global i18n key-usage scan (generalized from the equipment module's
 * scan).
 *
 * Two contracts are enforced for EVERY frontend module
 * (src/modules/<mod>/) plus the core namespaces
 * (src/i18n/locales/<lang>/<ns>.json):
 *
 * 1. Key presence — every static `t("key")` literal used in module code
 *    must resolve in all five language catalogs (through the i18next
 *    fallback namespace chain). Catches keys missing from ALL locales
 *    at once (rendered as raw keys), which catalog↔catalog parity tests
 *    cannot see.
 * 2. Interpolation — every key whose English value contains `{{var}}`
 *    placeholders must be called with all those variables at every
 *    static call site. Catches raw `{{list}}`/`{{count}}` leaking into
 *    user-visible toasts (the `added_toast` bug class).
 *
 * Two module kinds are covered:
 * - modules WITH a local catalog (src/modules/<mod>/i18n/en.json) — bare
 *   keys resolve against the module namespace (named after the module),
 * - modules WITHOUT a local catalog (e.g. settings, shared, spaces) —
 *   they have no namespace of their own, so their t() calls resolve
 *   against the core catalogs, exactly like at runtime: bare keys use
 *   defaultNS ("common", see src/i18n/config.ts), and keys under an
 *   explicit useTranslation("ns") / `ns:` prefix use that core or
 *   module namespace.
 *
 * Skipped on purpose:
 * - dynamic keys (template literals with `${}`) — not statically
 *   resolvable,
 * - call sites whose options object is a variable (not inline) — the
 *   scanner cannot prove variable content,
 * - test files themselves,
 * - modules without frontend source files (e.g. `vision` is backend-only).
 */

type Catalog = Record<string, unknown>;

const SRC = join(process.cwd(), "src");
const PLURAL_SUFFIXES = ["_zero", "_one", "_two", "_few", "_many", "_other"];
const CORE_NAMESPACES = [
  "auth",
  "categories",
  "common",
  "items",
  "labels",
  "modules",
  "onboarding",
  "scan",
  "locations",
];

function moduleList(): string[] {
  const modulesDir = join(SRC, "modules");
  return readdirSync(modulesDir).filter((m) =>
    existsSync(join(modulesDir, m, "i18n", "en.json")),
  );
}

/**
 * Modules WITHOUT a local i18n catalog (no src/modules/<mod>/i18n/en.json).
 * Their t() calls resolve against the core namespaces only — bare keys use
 * defaultNS ("common"), matching the runtime config in src/i18n/config.ts.
 */
function uncataloguedModules(): string[] {
  const modulesDir = join(SRC, "modules");
  return readdirSync(modulesDir).filter(
    (m) => !existsSync(join(modulesDir, m, "i18n", "en.json")),
  );
}

function catalogPath(ns: string, lang: string): string {
  return CORE_NAMESPACES.includes(ns)
    ? join(SRC, "i18n", "locales", lang, `${ns}.json`)
    : join(SRC, "modules", ns, "i18n", `${lang}.json`);
}

// Read once per file: every call site asks again, and the largest module
// has thousands of them — reading and parsing its catalogue per call is
// what took that module's case past its timeout on a loaded machine.
const catalogs = new Map<string, Catalog | null>();

function loadCatalog(ns: string, lang: string): Catalog | null {
  const path = catalogPath(ns, lang);
  if (!catalogs.has(path)) {
    catalogs.set(
      path,
      existsSync(path)
        ? (JSON.parse(readFileSync(path, "utf8")) as Catalog)
        : null,
    );
  }
  return catalogs.get(path) ?? null;
}

/**
 * Collects both leaf keys and object/array node keys (returnObjects
 * usage, e.g. `t("uomNames")` returning a map).
 */
function collectKeys(node: unknown, prefix: string[] = []): Set<string> {
  const out = new Set<string>();
  if (node == null) return out;
  if (typeof node === "string") {
    out.add(prefix.join("."));
    return out;
  }
  if (typeof node === "object") {
    if (prefix.length > 0) out.add(prefix.join("."));
    for (const [k, v] of Object.entries(node as Catalog)) {
      collectKeys(v, [...prefix, k]).forEach((x) => out.add(x));
    }
  }
  return out;
}

function resolveValue(ns: string, lang: string, key: string): unknown {
  const catalog = loadCatalog(ns, lang);
  if (!catalog) return undefined;
  let node: unknown = catalog;
  for (const segment of key.split(".")) {
    if (node == null || typeof node !== "object") return undefined;
    node = (node as Catalog)[segment];
  }
  return node;
}

const keySets = new Map<string, Set<string>>();

function keyExists(ns: string, lang: string, key: string): boolean {
  const catalog = loadCatalog(ns, lang);
  if (!catalog) return false;
  const cacheKey = `${ns}/${lang}`;
  if (!keySets.has(cacheKey)) keySets.set(cacheKey, collectKeys(catalog));
  const keys = keySets.get(cacheKey)!;
  if (keys.has(key)) return true;
  // Plural-only keys (no base, e.g. `lines` → `lines_one`/`lines_other`).
  return PLURAL_SUFFIXES.some((s) => keys.has(key + s));
}

function collectSourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "__tests__" || entry === "i18n") return [];
      return collectSourceFiles(full);
    }
    // A spec ships no strings, and it reaches for `t` in ways this scan
    // cannot follow — `i18n.getFixedT(null, "items")` names its namespace
    // where no hook and no prefix can be seen, so every key it checks looked
    // like a missing one. Specs under `__tests__/` were skipped already; the
    // ones sitting beside their component were not, which made the gate
    // depend on where a spec happens to live.
    if (/\.(test|spec)\.(ts|tsx)$/.test(entry)) return [];
    return /\.(ts|tsx)$/.test(entry) ? [full] : [];
  });
}

interface TCall {
  ns: string;
  fallbacks: string[];
  key: string;
  opts: string;
  hasOpts: boolean;
}

/**
 * Extract every static t() call from a source file. Namespaces resolve
 * per call site from the nearest preceding useTranslation() hook, with
 * an explicit `{ ns: "..." }` option or `ns:key` prefix taking priority.
 */
export function collectCalls(source: string, moduleNs: string): TCall[] {
  const calls: TCall[] = [];

  // All hook positions with their resolved namespace lists (fallbacks).
  // Supports aliased hooks (`const { t: tApprovals } = useTranslation("approvals")`).
  const hooks: Array<{
    index: number;
    alias: string;
    namespaces: string[];
  }> = [];
  const hookRe =
    /(?:const\s*\{\s*t(?:\s*:\s*(\w+))?\s*\}\s*=\s*)?useTranslation\(\s*(?:\[([^\]]*)\]|"([^"]+)")?\s*\)/g;
  for (const hm of source.matchAll(hookRe)) {
    const alias = hm[1] || "t";
    const namespaces = hm[2]
      ? [...hm[2].matchAll(/"([^"]+)"/g)].map((x) => x[1])
      : hm[3]
        ? [hm[3]]
        : ["common"];
    hooks.push({ index: hm.index ?? 0, alias, namespaces });
  }

  const callRe =
    /\b(t[A-Za-z0-9_]*)\s*\(\s*(?:"([^"]{1,200})"|'([^']{1,200})')\s*(?:,\s*(\{[^{}]*\}))?\s*\)/g;
  for (const m of source.matchAll(callRe)) {
    const fn = m[1];
    if (fn !== "t" && !hooks.some((h) => h.alias === fn)) continue; // not a t-function
    const rawKey = m[2] ?? m[3];
    if (!rawKey || rawKey.includes("${")) continue;
    const opts = m[4] ?? "";
    const pos = m.index ?? 0;
    const activeHook =
      [...hooks].reverse().find((h) => h.index <= pos && h.alias === fn) ??
      null;
    let namespaces = activeHook?.namespaces ?? [moduleNs];
    // `t` passed as a prop (no hook in file) → default ns, matching config.ts.
    if (!activeHook && fn === "t" && !source.includes("useTranslation")) {
      namespaces = ["common"];
    }

    // Explicit namespace option wins.
    const nsOpt = opts.match(/\bns\s*:\s*"([^"]+)"/);
    if (nsOpt) {
      namespaces = [nsOpt[1]];
    }

    let key = rawKey;
    if (key.includes(":")) {
      const [prefix, rest] = key.split(/:(.+)/);
      const known =
        CORE_NAMESPACES.includes(prefix) || moduleList().includes(prefix);
      if (known) {
        namespaces = [prefix];
        key = rest;
      }
    }
    calls.push({
      ns: namespaces[0] ?? moduleNs,
      fallbacks: namespaces.slice(1),
      key,
      opts,
      hasOpts: Boolean(m[4]),
    });
  }
  return calls;
}

/**
 * Variables a key requires, from the English catalog. When the base key
 * exists, only its own placeholders count (i18next without `count` uses
 * the base). When the base is missing, the plural variants' variables
 * union applies (the key is only reachable through a plural call).
 */
export function keyVariables(ns: string, key: string): Set<string> {
  const base = resolveValue(ns, "en", key);
  const variants = [key, ...PLURAL_SUFFIXES.map((s) => key + s)];
  const vars = new Set<string>();
  for (const variant of variants) {
    const value = resolveValue(ns, "en", variant);
    if (typeof value === "string") {
      for (const vm of value.matchAll(/\{\{(\w+)\}\}/g)) vars.add(vm[1]);
    }
  }
  if (typeof base === "string" && base.includes("{{")) return vars;
  if (base === undefined) return vars; // plural-only key → plural vars
  return new Set(); // base exists without placeholders → nothing required
}

/** Variables provided at an inline call site (shorthand-aware). */
export function providedVariables(opts: string): Set<string> {
  const provided = new Set<string>();
  const withoutStrings = opts
    .replace(/`[^`]*`/g, "`S`")
    .replace(/"([^"\\]|\\.)*"/g, '"S"')
    .replace(/'([^'\\]|\\.)*'/g, "'S'");
  for (const vm of withoutStrings.matchAll(
    /([A-Za-z_$][\w$]*)\s*(?=:|}|,|\))/g,
  )) {
    provided.add(vm[1]);
  }
  return provided;
}

export function findMissingVars(
  calls: TCall[],
): Array<{ ns: string; key: string; missing: string[] }> {
  const missing: Array<{ ns: string; key: string; missing: string[] }> = [];
  for (const call of calls) {
    const required = keyVariables(call.ns, call.key);
    if (required.size === 0) continue;
    if (!call.hasOpts) {
      missing.push({
        ns: call.ns,
        key: call.key,
        missing: [...required].sort(),
      });
      continue;
    }
    const provided = providedVariables(call.opts);
    const diff = [...required].filter((v) => !provided.has(v));
    if (diff.length > 0) {
      missing.push({ ns: call.ns, key: call.key, missing: diff.sort() });
    }
  }
  return missing;
}

function keyResolves(call: TCall, lang: string): boolean {
  if (keyExists(call.ns, lang, call.key)) return true;
  // Call sites with a `defaultValue` fallback never render a raw key —
  // i18next uses the default instead (same rule as check-i18n-keys.mjs).
  if (/\bdefaultValue\s*:/.test(call.opts)) return true;
  return call.fallbacks.some((fb) => keyExists(fb, lang, call.key));
}

/**
 * Modules whose catalog is addressed from outside the frontend: the backend
 * manifest names the keys (`label_key`, `title_key`, `description_key`) and a
 * generic renderer translates them, so there is no t() call site to find.
 * `vision` is the whole list — it has no screens of its own, it enters other
 * modules' flows.
 */
const KEYS_NAMED_BY_THE_BACKEND = new Set(["vision"]);

describe("global i18n key usage scan", () => {
  const modules = moduleList();
  const coreOnlyModules = uncataloguedModules();
  // Every frontend module is scanned. `defaultNs` is the fallback namespace
  // for bare t("key") calls when no hook/prefix provides one: the module's
  // own catalog when it exists, otherwise the runtime defaultNS ("common").
  const scopes = [
    ...modules.map((name) => ({ name, defaultNs: name })),
    ...coreOnlyModules.map((name) => ({ name, defaultNs: "common" })),
  ];

  it("finds at least the known modules with catalogs", () => {
    expect(modules.length).toBeGreaterThan(10);
    expect(modules).toContain("recipes");
    expect(modules).toContain("equipment");
  });

  it("covers modules that rely on core catalogs only", () => {
    // Regression guard: modules with t() calls but no local
    // catalog must not silently drop out of the scan again.
    expect(coreOnlyModules.length).toBeGreaterThan(0);
  });

  it.each(scopes)(
    "$name — every static t() key resolves in all 5 language catalogs",
    ({ name, defaultNs }) => {
      const sources = collectSourceFiles(join(SRC, "modules", name));
      if (sources.length === 0) return; // catalog with no frontend code at all
      const calls = sources.flatMap((file) =>
        collectCalls(readFileSync(file, "utf8"), defaultNs),
      );
      if (calls.length === 0) {
        // Not a free pass: a module that has code and translates nothing has
        // either dropped out of the scan or is one of the declared few whose
        // keys are named from the backend.
        expect(
          KEYS_NAMED_BY_THE_BACKEND.has(name),
          `${name} has frontend code but no t() call — did it fall out of the scan?`,
        ).toBe(true);
        return;
      }
      for (const lang of MAINTAINED_LANGUAGES) {
        for (const call of calls) {
          expect(
            keyResolves(call, lang),
            `${name}: key ${call.ns}:${call.key} missing in ${lang}`,
          ).toBe(true);
        }
      }
    },
  );

  it.each(scopes)(
    "$name — every {{var}} in used keys is provided at the call site",
    ({ name, defaultNs }) => {
      const sources = collectSourceFiles(join(SRC, "modules", name));
      if (sources.length === 0) return; // catalog with no frontend code at all
      const calls = sources.flatMap((file) =>
        collectCalls(readFileSync(file, "utf8"), defaultNs),
      );
      const missing = findMissingVars(calls);
      expect(missing).toEqual([]);
    },
  );

  it("fails on a synthetic missing key", () => {
    expect(keyExists("recipes", "en", "definitely.not.a.real.key")).toBe(false);
  });

  it("fails on a synthetic missing interpolation variable", () => {
    const result = findMissingVars([
      {
        ns: "recipes",
        fallbacks: [],
        key: "shopping.added_toast",
        opts: "{ count: 3 }",
        hasOpts: true,
      },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].missing).toContain("list");
  });
});
