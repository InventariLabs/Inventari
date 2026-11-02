/**
 * §14.2 — a place stock is kept has one name, and the register's picker keeps
 * it the same on every screen.
 *
 * /inventory/moves, /inventory/stock and /inventory/stock/as-of all offer the
 * same picker over the same records (`GET /locations`). The movements register
 * once said "Magazyn" while the stock register said "Lokalizacja" — one
 * filter, two names, two clicks apart, and only the Polish reader saw the split
 * because English said "Storage" in both. The names have since become one
 * word, Location (Miejsce, Lagerort, Emplacement, Ubicación); "storage",
 * "shelf" and the Polish "lokalizacja" are retired for it.
 *
 * So two assertions per language, against the movements register's own word:
 * every register screen uses that word, and no register string reaches for a
 * retired word to name it. A new screen joins an existing name rather than
 * inventing a sixth phrasing.
 *
 * The word check is a diacritic-insensitive stem match, which tolerates
 * inflection ("ubicación"/"ubicaciones", "miejsce"/"miejsca") without
 * tolerating a different noun.
 */
import { describe, expect, it } from "vitest";

import inventoryEn from "@/modules/inventory/i18n/en.json";
import inventoryDe from "@/modules/inventory/i18n/de.json";
import inventoryFr from "@/modules/inventory/i18n/fr.json";
import inventoryEs from "@/modules/inventory/i18n/es.json";
import inventoryPl from "@/modules/inventory/i18n/pl.json";

const CATALOGUES = {
  en: inventoryEn,
  de: inventoryDe,
  fr: inventoryFr,
  es: inventoryEs,
  pl: inventoryPl,
};

type Language = keyof typeof CATALOGUES;
type InventoryCatalogue = (typeof CATALOGUES)[Language];

/** The words the picker's name replaced — never to name the record again. */
const RETIRED_WORD: Record<Language, RegExp> = {
  en: /\bshel(?:f|ves)\b|\bstorages?\b/i,
  pl: /\blokalizacj\w*\b|\bmagazyn\w*\b/i,
  de: /\blagerplatz\w*\b|\blager\b|\blagern\b/i,
  fr: /\bentrep[ôo]ts?\b|\bstockage\b/i,
  es: /\balmac[ée]n(?:es)?\b/i,
};

/** The word without its last vowel, so "miejsce" also finds "miejsca". */
const stem = (value: string) => bare(value).replace(/[aeiouy]$/, "");

const bare = (value: string) =>
  value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();

export function pickerDivergences(
  lang: Language,
  cat: InventoryCatalogue,
): string[] {
  const word = cat.moves.filters.location;
  const found: string[] = [];

  if (cat.stock.filters.location !== word) {
    found.push(`stock.filters.location="${cat.stock.filters.location}"`);
  }
  if (cat.asOf.location !== word) {
    found.push(`asOf.location="${cat.asOf.location}"`);
  }
  if (cat.stock.filters.anyLocation !== cat.moves.filters.anyLocation) {
    found.push(`stock.filters.anyLocation="${cat.stock.filters.anyLocation}"`);
  }

  const namesTheRecord = {
    // The filtered empty state names the filters that are on; the one
    // filter that names a record — the location — is the phrase that has to
    // keep the picker's word.
    "moves.empty.filterNames.location": cat.moves.empty.filterNames.location,
    "moves.filters.oneStorage": cat.moves.filters.oneStorage,
    "stock.empty.filterNames.location": cat.stock.empty.filterNames.location,
    "stock.filters.oneStorage": cat.stock.filters.oneStorage,
    "stock.filters.includeEmpty": cat.stock.filters.includeEmpty,
  };
  for (const [key, value] of Object.entries(namesTheRecord)) {
    if (!bare(value).includes(stem(word))) {
      found.push(`${key}="${value}" does not name the record`);
    }
  }

  const retiredWord = RETIRED_WORD[lang];
  for (const [key, value] of Object.entries(namesTheRecord)) {
    if (retiredWord.test(value)) {
      found.push(`${key}="${value}" uses a retired word`);
    }
  }

  return found;
}

describe("the register's storage picker has one name per language", () => {
  for (const [lang, cat] of Object.entries(CATALOGUES)) {
    it(`names it the same on every register screen (${lang})`, () => {
      expect(pickerDivergences(lang as Language, cat)).toEqual([]);
    });
  }

  it("would catch the stock register inventing its own word", () => {
    const sabotaged = structuredClone(inventoryPl);
    sabotaged.stock.filters.location = "Lokalizacja";
    expect(pickerDivergences("pl", sabotaged)).toContain(
      'stock.filters.location="Lokalizacja"',
    );
  });

  it("would catch an empty state naming the record with a different noun", () => {
    const sabotaged = structuredClone(inventoryPl);
    sabotaged.stock.empty.filterNames.location =
      "lokalizacja: {{value}} — wyczyść ją, aby poszerzyć listę.";
    expect(pickerDivergences("pl", sabotaged)).toEqual(
      expect.arrayContaining([
        'stock.empty.filterNames.location="lokalizacja: {{value}} — wyczyść ją, aby poszerzyć listę." does not name the record',
        'stock.empty.filterNames.location="lokalizacja: {{value}} — wyczyść ją, aby poszerzyć listę." uses a retired word',
      ]),
    );
  });

  it("would catch an English empty state back on the shelf", () => {
    const sabotaged = structuredClone(inventoryEn);
    sabotaged.stock.empty.filterNames.location = "shelf: {{value}}";
    expect(pickerDivergences("en", sabotaged)).toContain(
      'stock.empty.filterNames.location="shelf: {{value}}" uses a retired word',
    );
  });
});
