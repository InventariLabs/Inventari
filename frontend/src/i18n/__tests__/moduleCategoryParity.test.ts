import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";

/**
 * Module-category label parity guard.
 *
 * One taxonomy reaches the user through two screens: the launcher renders it as
 * section headings (`launcher:sections.*`) and the module store as filter chips
 * (`common:appStore.category*`). They are two catalogs, so they can drift — and
 * they did: the store said "Podstawowe" while the launcher said "Rdzeń" for the
 * same set of modules.
 *
 * The invariants:
 *
 * 1. Every category is named in ALL five catalogs, on both screens.
 * 2. The two screens use the same word for the same category, per language.
 * 3. The English label carries no architecture vocabulary ("core") — the same
 *    rule `profileNameParity.test.ts` applies one storey up, and for the same
 *    reason: "core" is how the code is organized, not how the product is used.
 *
 * `appStore.categoryOther` has no launcher counterpart: the launcher assigns an
 * uncategorized module to "business" rather than showing a section for it.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "../..");

/** The launcher sections, in the order `Launcher.tsx` renders them. */
const CATEGORIES = [
  "core",
  "business",
  "analytics",
  "integrations",
  "system",
] as const;

function readJson(file: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
}

function launcherLabels(lang: string): Record<string, unknown> {
  const bundle = readJson(
    path.join(SRC, "modules", "launcher", "i18n", `${lang}.json`),
  );
  return (bundle.sections ?? {}) as Record<string, unknown>;
}

function storeLabels(lang: string): Record<string, unknown> {
  const bundle = readJson(
    path.join(SRC, "i18n", "locales", lang, "common.json"),
  );
  return (bundle.appStore ?? {}) as Record<string, unknown>;
}

function storeKey(category: string): string {
  return `category${category[0].toUpperCase()}${category.slice(1)}`;
}

describe("module category labels", () => {
  it("names every category on both screens, in all five languages", () => {
    const missing: string[] = [];
    for (const lang of MAINTAINED_LANGUAGES) {
      const launcher = launcherLabels(lang);
      const store = storeLabels(lang);
      for (const category of CATEGORIES) {
        if (typeof launcher[category] !== "string") {
          missing.push(`${lang}: launcher sections.${category}`);
        }
        if (typeof store[storeKey(category)] !== "string") {
          missing.push(`${lang}: common appStore.${storeKey(category)}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });

  it("uses one word per category, whichever screen shows it", () => {
    const drift: string[] = [];
    for (const lang of MAINTAINED_LANGUAGES) {
      const launcher = launcherLabels(lang);
      const store = storeLabels(lang);
      for (const category of CATEGORIES) {
        const here = launcher[category];
        const there = store[storeKey(category)];
        if (
          typeof here === "string" &&
          typeof there === "string" &&
          here !== there
        ) {
          drift.push(
            `${lang}/${category}: launcher says ${JSON.stringify(here)}, ` +
              `the module store says ${JSON.stringify(there)}`,
          );
        }
      }
    }
    expect(drift).toEqual([]);
  });

  it("keeps architecture vocabulary out of the English labels", () => {
    const problems: string[] = [];
    for (const category of CATEGORIES) {
      const label = launcherLabels("en")[category];
      if (typeof label === "string" && /\bcore\b/i.test(label)) {
        problems.push(
          `sections.${category} is ${JSON.stringify(label)} — "core" is an ` +
            `architecture word, not a user concept`,
        );
      }
    }
    expect(problems).toEqual([]);
  });
});
