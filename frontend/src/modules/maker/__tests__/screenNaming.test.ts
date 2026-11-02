import { describe, expect, it } from "vitest";
import en from "@/modules/maker/i18n/en.json";
import pl from "@/modules/maker/i18n/pl.json";
import de from "@/modules/maker/i18n/de.json";
import fr from "@/modules/maker/i18n/fr.json";
import es from "@/modules/maker/i18n/es.json";
import itemsEn from "@/i18n/locales/en/items.json";
import itemsPl from "@/i18n/locales/pl/items.json";
import itemsDe from "@/i18n/locales/de/items.json";
import itemsFr from "@/i18n/locales/fr/items.json";
import itemsEs from "@/i18n/locales/es/items.json";

/**
 * The catalog screen showed BOMs under the heading "Twoje produkty",
 * while "Produkty" is what `/inventory/items` calls itself. Someone walking
 * into their products found an empty list of BOMs and concluded the data was
 * gone. A page title has to be free across the application, not just inside
 * its own module.
 */
const CATALOGS = [
  ["en", en, itemsEn],
  ["pl", pl, itemsPl],
  ["de", de, itemsDe],
  ["fr", fr, itemsFr],
  ["es", es, itemsEs],
] as const;

const normalize = (value: string) => value.trim().toLowerCase();

describe("maker screen naming", () => {
  it.each(CATALOGS)(
    "%s does not name the BOM catalog after the items screen",
    (_lang, catalog, items) => {
      expect(normalize(catalog.catalog.title)).not.toContain(
        normalize(items.title),
      );
    },
  );

  it.each(CATALOGS)(
    "%s calls creating a BOM the same thing in the header and in the empty state",
    (_lang, catalog) => {
      expect(catalog.catalog.empty.cta).toBe(catalog.catalog.newRecipe);
    },
  );

  it.each(CATALOGS)(
    "%s subtitles the runs screen with the runs screen, not the module",
    (_lang, catalog) => {
      // The module blurb lives in launcher.description; a screen subtitle that
      // lists the module's other screens sends people to the wrong one.
      expect(catalog.productionList.subtitle).not.toBe(
        catalog.launcher.description,
      );
      expect(normalize(catalog.productionList.subtitle)).not.toContain(
        normalize(catalog.catalog.title),
      );
    },
  );
});
