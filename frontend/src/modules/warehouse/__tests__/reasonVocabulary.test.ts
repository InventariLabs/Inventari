import { describe, expect, it } from "vitest";

import en from "../i18n/en.json";
import pl from "../i18n/pl.json";
import de from "../i18n/de.json";
import fr from "../i18n/fr.json";
import es from "../i18n/es.json";

/**
 * One concept, one word.
 *
 * A correction raised for the wrong product and a return of the wrong item
 * are the same situation. Both windows open from the same document, one click
 * apart, and offered it under two names — "Wrong product" beside "Wrong item",
 * "Zły produkt" beside "Nie ten towar", "Falsches Produkt" beside "Falscher
 * Artikel", "Produit erroné" beside "Mauvais article", "Producto incorrecto"
 * beside "Artículo incorrecto" — so the discrepancy report had two
 * vocabularies for one reason.
 *
 * The enums stay distinct: `WRONG_PRODUCT` and `WRONG_ITEM` are the backend's
 * codes and the reports count them. What a reader meets is one word per
 * concept, in all five languages (§14.3: the stocked record is a Product).
 */
const CATALOGUES: Record<string, unknown> = { en, pl, de, fr, es };

type CorrectionCatalogue = {
  reasons: {
    correction: { codes: Record<string, string> };
    return: { codes: Record<string, string> };
  };
};

/** The return's name for the wrong product, against the correction's. */
export function wrongProductDivergence(catalog: unknown): string | null {
  const { correction, return: returned } = (catalog as CorrectionCatalogue)
    .reasons;
  const correctionName = correction.codes.WRONG_PRODUCT;
  const returnName = returned.codes.WRONG_ITEM;
  return returnName === correctionName
    ? null
    : `return "${returnName}" vs correction "${correctionName}"`;
}

describe("the correction and the return name the wrong product with one word", () => {
  for (const [language, catalog] of Object.entries(CATALOGUES)) {
    it(`agrees in ${language}`, () => {
      expect(wrongProductDivergence(catalog)).toBeNull();
    });
  }

  it("would catch the two lists drifting apart again", () => {
    const fixture = {
      reasons: {
        correction: { codes: { WRONG_PRODUCT: "Wrong product" } },
        return: { codes: { WRONG_ITEM: "Wrong item" } },
      },
    };

    expect(wrongProductDivergence(fixture)).toBe(
      'return "Wrong item" vs correction "Wrong product"',
    );
  });
});
