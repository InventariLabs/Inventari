/**
 * Where goods LAND is named after the destination, on every screen that asks.
 *
 * Production and cook-for-stock both named that field with a word meaning the
 * opposite: "Output storage" / "Magazyn wyjściowy" / "Stockage de sortie" /
 * "Almacén de salida", each of them one line under a subtitle promising a
 * TARGET place. In Polish "magazyn wyjściowy" is the source — the exact
 * reverse of the movement the field describes, and nothing downstream
 * questions the choice.
 *
 * The app already has a word for this, used by documents, purchase orders,
 * equipment and the archive dialog. These two fields join it rather than
 * inventing a sixth phrasing, so the assertion is against the established
 * wording rather than a literal repeated here.
 */
import { describe, expect, it } from "vitest";

import documentsEn from "@/modules/warehouse/i18n/en.json";
import documentsPl from "@/modules/warehouse/i18n/pl.json";
import documentsDe from "@/modules/warehouse/i18n/de.json";
import documentsFr from "@/modules/warehouse/i18n/fr.json";
import documentsEs from "@/modules/warehouse/i18n/es.json";
import makerEn from "@/modules/maker/i18n/en.json";
import makerPl from "@/modules/maker/i18n/pl.json";
import makerDe from "@/modules/maker/i18n/de.json";
import makerFr from "@/modules/maker/i18n/fr.json";
import makerEs from "@/modules/maker/i18n/es.json";
import recipesEn from "@/modules/recipes/i18n/en.json";
import recipesPl from "@/modules/recipes/i18n/pl.json";
import recipesDe from "@/modules/recipes/i18n/de.json";
import recipesFr from "@/modules/recipes/i18n/fr.json";
import recipesEs from "@/modules/recipes/i18n/es.json";

const CATALOGUES = {
  en: { documents: documentsEn, maker: makerEn, recipes: recipesEn },
  pl: { documents: documentsPl, maker: makerPl, recipes: recipesPl },
  de: { documents: documentsDe, maker: makerDe, recipes: recipesDe },
  fr: { documents: documentsFr, maker: makerFr, recipes: recipesFr },
  es: { documents: documentsEs, maker: makerEs, recipes: recipesEs },
};

describe("the field that receives produced goods", () => {
  for (const [lang, cat] of Object.entries(CATALOGUES)) {
    // Case is the label's own business; the words are not.
    const established = cat.documents.fields.targetLocation.toLowerCase();

    it(`is named after the destination on the production sheet (${lang})`, () => {
      expect(cat.maker.create.storageLabel.toLowerCase()).toBe(established);
    });

    it(`is named the same on the cook-for-stock window (${lang})`, () => {
      expect(cat.recipes.cookForStock.storageLabel.toLowerCase()).toBe(
        established,
      );
    });
  }
});
