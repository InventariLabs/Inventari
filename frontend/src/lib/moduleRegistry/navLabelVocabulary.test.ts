import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { moduleRegistry } from "../moduleRegistry";
import { type Language } from "@/i18n/languages";
import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";

// Registering every real module, the same way App.tsx does.
import.meta.glob("../../modules/*/module.ts", { eager: true });

/**
 * The tab and the page under it say one word.
 *
 * With the Equipment module enabled, the inventory navigation promised
 * "Assets" and "Locations" while the pages under those tabs were still headed
 * "Products" and "Storages" — a reader followed a word and met a different
 * one at the destination. "Assets" also already meant the module's own
 * fixed-asset list, so one word carried two meanings in one application.
 *
 * The module had renamed exactly the two navigation keys
 * (`inventory:nav.items`, `inventory:nav.storages`) and stopped at the tab
 * strip; the page titles, subtitles, buttons and counters were not in the
 * declaration and stayed on the core vocabulary. That is why no module renames
 * a core label alone any more: a rename of a tab carries the page title it
 * opens, or it does not happen.
 *
 * The rule reads the pairing out of the inventory module's own declaration
 * rather than a list copied here, and applies whatever the enabled modules
 * override — so a future module that renames both together is welcome.
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "../..");

function readJson(file: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
}

/** language → the three catalogs the pairs below resolve against, read from
 *  the shipped files — one entry per `MAINTAINED_LANGUAGES` language, so a
 *  language added per the recipe is checked without any list being edited. */
const CATALOGUES: Record<string, Record<string, unknown>> = Object.fromEntries(
  MAINTAINED_LANGUAGES.map((language) => [
    language,
    {
      inventory: readJson(
        path.join(SRC, "modules", "inventory", "i18n", `${language}.json`),
      ),
      items: readJson(
        path.join(SRC, "i18n", "locales", language, "items.json"),
      ),
      locations: readJson(
        path.join(SRC, "i18n", "locales", language, "locations.json"),
      ),
    },
  ]),
);

/**
 * Tab → the page title it opens. The pairs come from the inventory module's
 * declaration (`moduleNav.items[].labelKey` / `titleKey`), resolved against
 * the core catalogues; only the pairs whose title is a core page title are
 * listed, because a tab without a page of its own has no title to match.
 */
const NAV_TITLE_PAIRS = [
  { labelKey: "inventory:nav.items", titleKey: "items:title" },
  { labelKey: "inventory:nav.storages", titleKey: "locations:title" },
  { labelKey: "inventory:nav.stock", titleKey: "inventory:stock.title" },
  { labelKey: "inventory:nav.moves", titleKey: "inventory:moves.title" },
];

function resolve(language: Language, key: string): string {
  const [namespace, path] = key.split(":");
  let node: unknown = CATALOGUES[language][namespace];
  for (const segment of path.split(".")) {
    node =
      node && typeof node === "object"
        ? (node as Record<string, unknown>)[segment]
        : undefined;
  }
  if (typeof node !== "string") {
    throw new Error(`${key} is not a string in ${language}`);
  }
  return node;
}

/** Every override the enabled modules declare, `lang -> key -> value`. */
export function declaredOverrides(): Record<string, Record<string, string>> {
  const byLanguage: Record<string, Record<string, string>> = {};
  for (const name of moduleRegistry.getAllRegisteredModules()) {
    const overrides = moduleRegistry.getModule(name)?.i18nOverrides;
    if (!overrides) continue;
    for (const [language, values] of Object.entries(overrides)) {
      byLanguage[language] = { ...byLanguage[language], ...values };
    }
  }
  return byLanguage;
}

export function unpairedTabs(
  overrides: Record<string, Record<string, string>>,
): string[] {
  const found: string[] = [];
  for (const language of MAINTAINED_LANGUAGES) {
    for (const { labelKey, titleKey } of NAV_TITLE_PAIRS) {
      const label =
        overrides[language]?.[labelKey] ?? resolve(language, labelKey);
      const title =
        overrides[language]?.[titleKey] ?? resolve(language, titleKey);
      // A tab may be shorter than its page's heading ("Stock" opens "Stock
      // levels") — it may not be a different word.
      if (!title.toLowerCase().includes(label.toLowerCase())) {
        found.push(
          `${language}: "${label}" (${labelKey}) → "${title}" (${titleKey})`,
        );
      }
    }
  }
  return found;
}

describe("a tab and the page it opens say one word", () => {
  it("holds for every language on the shipped catalogues", () => {
    expect(unpairedTabs({})).toEqual([]);
  });

  it("holds under whatever the enabled modules rename", () => {
    expect(unpairedTabs(declaredOverrides())).toEqual([]);
  });

  it("would catch the equipment rename that stopped at the tab strip", () => {
    const preFix = {
      en: { "inventory:nav.items": "Assets" },
      pl: { "inventory:nav.items": "Zasoby" },
    };

    expect(unpairedTabs(preFix)).toEqual([
      'en: "Assets" (inventory:nav.items) → "Products" (items:title)',
      'pl: "Zasoby" (inventory:nav.items) → "Produkty" (items:title)',
    ]);
  });
});
