/**
 * One concept, one word (UI_GUIDELINES §14.3).
 *
 * The thing on a shelf is a **Product**. It used to be called two things at
 * once: the sidebar and the page title said "Items" while the subtitle
 * directly beneath them said "Browse and manage your products", and one
 * sentence in the bulk-edit window managed both nouns in a single breath —
 * "applied to all 3 selected products … unchanged for each item".
 *
 * Scope is the core catalogues: the ones where the noun can only mean the
 * stocked record. Module catalogues are deliberately out — `warehouse`,
 * `purchase_orders`, `shopping_lists` and `stock_takes` use "item" for a
 * *line of a list*, which is a different concept that happens to share the
 * English word, and sorting those apart is a judgement per string rather
 * than a rule.
 *
 * Each language bans its own second noun. Polish is checked for "przedmiot"
 * but not for "pozycja": that word is also the ordinary Polish for a
 * position on a shelf, which is what `itemShelfLocation` means.
 *
 * Internal identifiers may lag behind — the model is `Item`, the route is
 * `/inventory/items`, and both stay. User-visible strings may not.
 */
import { describe, expect, it } from "vitest";

import commonEn from "@/i18n/locales/en/common.json";
import itemsEn from "@/i18n/locales/en/items.json";
import storagesEn from "@/i18n/locales/en/locations.json";
import labelsEn from "@/i18n/locales/en/labels.json";
import scanEn from "@/i18n/locales/en/scan.json";
import inventoryEn from "@/modules/inventory/i18n/en.json";

import commonPl from "@/i18n/locales/pl/common.json";
import itemsPl from "@/i18n/locales/pl/items.json";
import storagesPl from "@/i18n/locales/pl/locations.json";
import labelsPl from "@/i18n/locales/pl/labels.json";
import inventoryPl from "@/modules/inventory/i18n/pl.json";

import commonDe from "@/i18n/locales/de/common.json";
import itemsDe from "@/i18n/locales/de/items.json";
import storagesDe from "@/i18n/locales/de/locations.json";
import labelsDe from "@/i18n/locales/de/labels.json";
import inventoryDe from "@/modules/inventory/i18n/de.json";

import commonFr from "@/i18n/locales/fr/common.json";
import itemsFr from "@/i18n/locales/fr/items.json";
import storagesFr from "@/i18n/locales/fr/locations.json";
import labelsFr from "@/i18n/locales/fr/labels.json";
import inventoryFr from "@/modules/inventory/i18n/fr.json";

import commonEs from "@/i18n/locales/es/common.json";
import itemsEs from "@/i18n/locales/es/items.json";
import storagesEs from "@/i18n/locales/es/locations.json";
import labelsEs from "@/i18n/locales/es/labels.json";
import inventoryEs from "@/modules/inventory/i18n/es.json";

const BANNED: Record<string, RegExp> = {
  en: /\bitems?\b/i,
  pl: /\bprzedmiot\w*\b/i,
  de: /\bArtikeln?\b/i,
  fr: /\barticles?\b/i,
  es: /\bart[íi]culos?\b/i,
};

/**
 * "Where do you keep your things?" opens the storage wizard in all five
 * languages before the interface has named anything — a conversational
 * question, not a second name for the record.
 */
const CONVERSATIONAL = [/^onboarding\.step1Title$/];

function visibleStrings(
  node: unknown,
  path = "",
): Array<{ path: string; value: string }> {
  if (typeof node === "string") return [{ path, value: node }];
  if (Array.isArray(node)) {
    return node.flatMap((v, i) => visibleStrings(v, `${path}[${i}]`));
  }
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([k, v]) =>
      visibleStrings(v, path ? `${path}.${k}` : k),
    );
  }
  return [];
}

export function offenders(catalogues: unknown[], pattern: RegExp) {
  return catalogues.flatMap((catalogue) =>
    visibleStrings(catalogue)
      .filter(({ path }) => !CONVERSATIONAL.some((re) => re.test(path)))
      .filter(({ value }) => pattern.test(value)),
  );
}

describe("the record has one name, and it is Product", () => {
  it.each([
    ["en", [itemsEn, commonEn, storagesEn, labelsEn, scanEn, inventoryEn]],
    ["pl", [itemsPl, commonPl, storagesPl, labelsPl, inventoryPl]],
    ["de", [itemsDe, commonDe, storagesDe, labelsDe, inventoryDe]],
    ["fr", [itemsFr, commonFr, storagesFr, labelsFr, inventoryFr]],
    ["es", [itemsEs, commonEs, storagesEs, labelsEs, inventoryEs]],
  ])("names no second word for it in %s", (lang, catalogues) => {
    expect(offenders(catalogues, BANNED[lang])).toEqual([]);
  });

  it("would catch the noun coming back", () => {
    expect(offenders([{ title: "Items" }], BANNED.en)).toEqual([
      { path: "title", value: "Items" },
    ]);
  });

  it("leaves the wizard's opening question alone", () => {
    expect(
      offenders(
        [{ onboarding: { step1Title: "Where are your items?" } }],
        BANNED.en,
      ),
    ).toEqual([]);
  });
});
