/*
 * — i18n parity guard for the rentals module.
 *
 * The render tests mock i18n, so a key missing from a real catalog would go
 * unnoticed there. This test reads the six catalogs and holds them to the
 * English one, plural suffixes included.
 */

import { describe, expect, it } from "vitest";

import en from "../i18n/en.json";
import pl from "../i18n/pl.json";
import de from "../i18n/de.json";
import fr from "../i18n/fr.json";
import es from "../i18n/es.json";
import pt from "../i18n/pt.json";

type Catalog = Record<string, unknown>;

const catalogs: Record<string, Catalog> = {
  en: en as unknown as Catalog,
  pl: pl as unknown as Catalog,
  de: de as unknown as Catalog,
  fr: fr as unknown as Catalog,
  es: es as unknown as Catalog,
  pt: pt as unknown as Catalog,
};

function leaves(node: unknown, prefix = ""): string[] {
  if (node === null || typeof node !== "object" || Array.isArray(node)) {
    return [prefix];
  }
  return Object.entries(node as Catalog).flatMap(([key, value]) =>
    leaves(value, prefix ? `${prefix}.${key}` : key),
  );
}

function get(node: unknown, key: string): unknown {
  let current: unknown = node;
  for (const part of key.split(".")) {
    if (
      current &&
      typeof current === "object" &&
      part in (current as Catalog)
    ) {
      current = (current as Catalog)[part];
    } else {
      return undefined;
    }
  }
  return current;
}

const englishLeaves = leaves(en);

describe("rentals i18n", () => {
  it.each(Object.entries(catalogs))(
    "%s carries every English key with a non-empty value",
    (lang, catalog) => {
      for (const key of englishLeaves) {
        if (lang === "en") continue;
        // Plural families: a base key in English is satisfied by variants.
        if (
          typeof get(en, key) === "string" &&
          get(catalog, key) === undefined
        ) {
          const suffixSatisfied = ["_one", "_few", "_many", "_other"].some(
            (suffix) =>
              get(catalog, key.replace(/_other$/, suffix)) !== undefined,
          );
          if (!suffixSatisfied) {
            expect(
              get(catalog, key),
              `${lang} is missing ${key}`,
            ).toBeDefined();
          }
          continue;
        }
        const value = get(catalog, key);
        expect(value, `${lang} is missing ${key}`).toBeDefined();
        expect(
          String(value).trim().length,
          `${lang} has an empty ${key}`,
        ).toBeGreaterThan(0);
      }
    },
  );

  it("pl carries _few and _many for every plural family", () => {
    const pluralBases = new Set(
      englishLeaves
        .filter((key) => key.endsWith("_other"))
        .map((key) => key.replace(/_other$/, "")),
    );
    for (const base of pluralBases) {
      for (const suffix of ["_one", "_few", "_many", "_other"]) {
        expect(get(pl, `${base}${suffix}`), `${base}${suffix}`).toBeDefined();
      }
    }
  });

  it("every catalog names the module the same way as the registry", () => {
    for (const [lang, catalog] of Object.entries(catalogs)) {
      expect(get(catalog, "navigation.title"), lang).toBe(
        get(catalog, "title"),
      );
    }
  });
});
