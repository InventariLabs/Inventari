/*
 * — i18n parity guard for the stock takes module.
 *
 * Catalog-level test: the i18n mock used in render tests resolves keys
 * across namespaces, so missing keys in this module would go unnoticed
 * there. This test asserts the real JSON catalogs directly.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

import en from "./i18n/en.json";
import pl from "./i18n/pl.json";
import de from "./i18n/de.json";
import fr from "./i18n/fr.json";
import es from "./i18n/es.json";

type Catalog = Record<string, unknown>;

const catalogs: Record<string, Catalog> = {
  en: en as unknown as Catalog,
  pl: pl as unknown as Catalog,
  de: de as unknown as Catalog,
  fr: fr as unknown as Catalog,
  es: es as unknown as Catalog,
};

const STATUSES = ["draft", "in_progress", "completed", "cancelled"] as const;

function pathGet(node: unknown, dottedKey: string): unknown {
  const parts = dottedKey.split(".");
  let cur: unknown = node;
  for (const p of parts) {
    if (cur && typeof cur === "object" && p in (cur as Catalog)) {
      cur = (cur as Catalog)[p];
    } else {
      return undefined;
    }
  }
  return cur;
}

describe(" i18n parity (5 languages)", () => {
  it.each(Object.entries(catalogs))(
    "%s has translated statuses without raw key prefixes",
    (_lang, catalog) => {
      for (const status of STATUSES) {
        const value = pathGet(catalog, `statuses.${status}`);
        expect(typeof value).toBe("string");
        const text = String(value);
        expect(text.trim().length).toBeGreaterThan(0);
        // Rendering the raw key ("statuses.in_progress") is the bug.
        expect(text).not.toMatch(/^statuses\./i);
        expect(text).not.toContain("STATUSES.");
      }
    },
  );

  it.each(Object.entries(catalogs))(
    "%s has label keys for missing/surplus and add-new-item",
    (_lang, catalog) => {
      for (const key of [
        "discrepancyMissing",
        "discrepancySurplus",
        "addNewItem",
      ]) {
        const value = pathGet(catalog, key);
        expect(typeof value).toBe("string");
        expect(String(value).trim().length).toBeGreaterThan(0);
      }
    },
  );

  it.each(Object.entries(catalogs))(
    "%s has plural forms for the progress sentences",
    (_lang, catalog) => {
      // The bare `discrepancies` badge plurals are gone: the report names
      // its difference kinds explicitly now, and an unused plural is a lie
      // the catalogue keeps telling.
      const detOne = pathGet(catalog, "progress.discrepanciesDetected_one");
      const detOther = pathGet(catalog, "progress.discrepanciesDetected_other");
      expect(typeof detOne).toBe("string");
      expect(typeof detOther).toBe("string");
      // The count must sit inside the sentence, not be glued before it.
      expect(String(detOther)).toContain("{{count}}");
    },
  );

  it("pl has _few and _many forms for Polish declension", () => {
    for (const key of ["progress.discrepanciesDetected"]) {
      expect(typeof pathGet(catalogs.pl, `${key}_few`)).toBe("string");
      expect(typeof pathGet(catalogs.pl, `${key}_many`)).toBe("string");
    }
  });

  it.each(Object.entries(catalogs))(
    "%s inflects the completion confirmation instead of escaping into parentheses",
    (_lang, catalog) => {
      // The dialog that overwrites the counted stock with the counted numbers
      // said "1 produktów" in Polish and "1 product(s)" in English and
      // "1 Produkt(en)" in German. Every language writes its own singular
      // now, and the count sits inside the sentence rather than beside it.
      const one = pathGet(catalog, "confirm.complete.message_one");
      const other = pathGet(catalog, "confirm.complete.message_other");
      expect(typeof one).toBe("string");
      expect(typeof other).toBe("string");
      // The singular has no number left to interpolate — it names one thing.
      expect(String(one)).not.toContain("{{count}}");
      expect(String(other)).toContain("{{count}}");
      // The parenthesised escape is the defect, not a style: it is the same
      // bytes in every language.
      expect(String(one)).not.toMatch(/\((?:s|en|e)\)/);
      expect(String(other)).not.toMatch(/\((?:s|en|e)\)/);
    },
  );

  it("pl carries _few and _many for the completion confirmation", () => {
    for (const suffix of ["_few", "_many"]) {
      expect(
        typeof pathGet(catalogs.pl, `confirm.complete.message${suffix}`),
      ).toBe("string");
    }
  });

  it.each(Object.entries(catalogs))(
    "%s progress.countedOf interpolates both numbers",
    (_lang, catalog) => {
      const value = String(pathGet(catalog, "progress.countedOf"));
      expect(value).toContain("{{counted}}");
      expect(value).toContain("{{total}}");
    },
  );

  it("i18n catalogs are valid JSON files on disk", () => {
    const dir = path.resolve(__dirname, "./i18n");
    for (const lang of Object.keys(catalogs)) {
      const raw = fs.readFileSync(path.join(dir, `${lang}.json`), "utf-8");
      expect(() => JSON.parse(raw)).not.toThrow();
    }
  });
});
