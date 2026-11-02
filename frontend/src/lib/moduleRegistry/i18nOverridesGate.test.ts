import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join } from "node:path";

import { moduleRegistry } from "../moduleRegistry";
import type { FrontendModule } from "./moduleInterfaces";
import { servedNamespaces } from "@/i18n/config";
import { SUPPORTED_LANGUAGES } from "@/i18n/languages";
import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";

/**
 * The "Changes the interface" gate: every i18n override a module declares
 * must target a key that exists in the shipped bundles, that some code
 * actually reads, and a namespace whose catalogs the dynamic backend
 * announces. An override without a reader used to sit in the registry
 * doing nothing — the badge promised a change the screen never showed
 * (the equipment module renamed `common:navigation.items` while the sidebar
 * reads `inventory:nav.items`). A namespace the backend never serves is the
 * same kind of silence with a longer fuse: no catalog ever lands for it, so
 * the re-application that keeps a standing override on top after a late
 * catalog or a language switch can never fire. `noteCatalogLanded` keys on
 * the (language, namespace) pair a landing catalog carries, and only
 * `src/i18n/config.ts`'s served namespaces land.
 */

// Registering every real module, the same way App.tsx does.
import.meta.glob("../../modules/*/module.ts", { eager: true });

const SRC_ROOT = join(__dirname, "../..");

function localeBundle(
  lang: string,
  ns: string,
): Record<string, unknown> | null {
  const corePath = join(SRC_ROOT, "i18n/locales", lang, `${ns}.json`);
  const modulePath = join(SRC_ROOT, "modules", ns, "i18n", `${lang}.json`);
  const path = existsSync(corePath)
    ? corePath
    : existsSync(modulePath)
      ? modulePath
      : null;
  if (!path) return null;
  return JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
}

function resolvePath(bundle: Record<string, unknown>, path: string[]): unknown {
  let node: unknown = bundle;
  for (const segment of path) {
    if (typeof node !== "object" || node === null) return undefined;
    node = (node as Record<string, unknown>)[segment];
  }
  return node;
}

function* walkSources(dir: string): Generator<string> {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "node_modules" || entry.startsWith(".")) continue;
      yield* walkSources(full);
    } else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.(ts|tsx)$/.test(entry)) {
      yield full;
    }
  }
}

// file path → content, built once for all override keys
let corpus: Map<string, string> | null = null;
function sourceCorpus(): Map<string, string> {
  if (!corpus) {
    corpus = new Map();
    for (const file of walkSources(SRC_ROOT)) {
      corpus.set(file, readFileSync(file, "utf8"));
    }
  }
  return corpus;
}

function hasReader(key: string, declaringModule: string): boolean {
  const sep = key.indexOf(":");
  const barePath = sep === -1 ? key : key.slice(sep + 1);
  const needles = sep === -1 ? [key, `common:${key}`] : [key, barePath];
  for (const [file, content] of sourceCorpus()) {
    // The declaration itself is not a reader.
    if (file.endsWith(join("modules", declaringModule, "module.ts"))) continue;
    if (needles.some((needle) => content.includes(needle))) return true;
  }
  return false;
}

/**
 * Override namespaces the backend never announces, keyed `module:namespace`.
 *
 * The ordering guarantee — re-applying a standing override after a catalog
 * lands, so a late chunk or a language switch cannot bury it — is keyed on
 * the (language, namespace) pair the catalog lands under. Only
 * `src/i18n/config.ts`'s served namespaces ever produce such a landing, so
 * an override into any other namespace has no catalog event behind it: the
 * registry would hold a rename nothing re-applies.
 *
 * `served` is a parameter so the check's teeth can be measured against a
 * planted namespace no catalog serves, not only against the live tree.
 */
export function unservedOverrideNamespaces(
  modules: ReadonlyArray<Pick<FrontendModule, "name" | "i18nOverrides">>,
  served: ReadonlySet<string>,
): string[] {
  const problems: string[] = [];
  for (const mod of modules) {
    const namespaces = new Set<string>();
    Object.values(mod.i18nOverrides ?? {}).forEach((langOverrides) =>
      Object.keys(langOverrides).forEach((key) => {
        const sep = key.indexOf(":");
        namespaces.add(sep === -1 ? "common" : key.slice(0, sep));
      }),
    );
    for (const ns of namespaces) {
      if (!served.has(ns)) problems.push(`${mod.name}:${ns}`);
    }
  }
  return problems;
}

describe("i18n overrides gate", () => {
  const modulesWithOverrides = moduleRegistry
    .getAllRegisteredModules()
    .map((name) => moduleRegistry.getModule(name))
    .filter((mod) => mod && Object.keys(mod.i18nOverrides ?? {}).length > 0);

  it("at least one module declares overrides, or the gate is vacuous", () => {
    // Not a failure condition — but if this ever reads zero while the badge
    // still exists, the gate stopped guarding anything.
    expect(modulesWithOverrides.length).toBeGreaterThanOrEqual(0);
  });

  modulesWithOverrides.forEach((mod) => {
    const overrides = mod!.i18nOverrides!;
    describe(mod!.name, () => {
      it("covers every maintained language, and only shipped ones", () => {
        // A community language falls back to English per key: it may carry
        // overrides, but no change has to write them.
        const covered = Object.keys(overrides);
        expect(covered).toEqual(
          expect.arrayContaining([...MAINTAINED_LANGUAGES]),
        );
        expect([...SUPPORTED_LANGUAGES]).toEqual(
          expect.arrayContaining(covered),
        );
      });

      it("every override key exists in the shipped bundles", () => {
        for (const [lang, langOverrides] of Object.entries(overrides)) {
          for (const key of Object.keys(langOverrides)) {
            const sep = key.indexOf(":");
            const ns = sep === -1 ? "common" : key.slice(0, sep);
            const path = (sep === -1 ? key : key.slice(sep + 1)).split(".");
            const bundle = localeBundle(lang, ns);
            expect(
              bundle,
              `${mod!.name}: no ${lang} bundle for namespace "${ns}" (key "${key}")`,
            ).not.toBeNull();
            expect(
              resolvePath(bundle!, path),
              `${mod!.name}: "${key}" does not exist in the ${lang} bundle — ` +
                "an override of a missing key adds a label instead of renaming one",
            ).toBeTypeOf("string");
          }
        }
      });

      it("every override key has a reader outside the declaring module", () => {
        const keys = new Set<string>();
        Object.values(overrides).forEach((langOverrides) =>
          Object.keys(langOverrides).forEach((key) => keys.add(key)),
        );
        for (const key of keys) {
          expect(
            hasReader(key, mod!.name),
            `${mod!.name}: nothing in src/ reads "${key}" — the override ` +
              "would change a label no screen renders",
          ).toBe(true);
        }
      });
    });
  });

  describe("every override namespace is one a catalog can land in", () => {
    it("rejects an override into a namespace no catalog serves", () => {
      const planted: FrontendModule = {
        name: "test-gate-planted",
        routes: [],
        i18nOverrides: { en: { "phantom-ns:title": "Phantom" } },
      };

      expect(
        unservedOverrideNamespaces(
          [planted],
          new Set(["common", "items", "locations"]),
        ),
      ).toEqual(["test-gate-planted:phantom-ns"]);
    });

    it("finds every live override inside a served namespace", () => {
      const liveModules = modulesWithOverrides.filter(
        (mod): mod is FrontendModule => mod !== undefined,
      );

      expect(
        unservedOverrideNamespaces(liveModules, servedNamespaces()),
      ).toEqual([]);
    });
  });
});
