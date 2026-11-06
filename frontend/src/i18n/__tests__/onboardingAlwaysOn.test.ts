/**
 * The module step lists what is always on under the optional Warehouse
 * module. The sentence names *locations* — the warehouse is a module the
 * reader may untick one line above. German, French and Spanish once said
 * "Lager / entrepôts / almacenes" there, which reads as the opposite.
 */
import { describe, expect, it } from "vitest";

import en from "../locales/en/onboarding.json";
import de from "../locales/de/onboarding.json";
import fr from "../locales/fr/onboarding.json";
import es from "../locales/es/onboarding.json";
import pl from "../locales/pl/onboarding.json";
import pt from "../locales/pt/onboarding.json";

const LOCATION_WORD: Record<string, RegExp> = {
  en: /locations/i,
  de: /Lagerorte/,
  fr: /emplacements/i,
  es: /ubicaciones/i,
  pl: /miejsca/i,
  pt: /locais|localizações/i,
};
const WAREHOUSE_WORD =
  /\b(Lager|entrepôts?|almacenes|warehouses?|magazyn\w*|armazéns?)\b/i;

// Statistics and label printing are on in every organisation too
// (`ALWAYS_ON_MODULES` in the backend); a footer that listed only three
// modules promised the reader could switch the other two off.
const STATS_WORD: Record<string, RegExp> = {
  en: /statistics/i,
  de: /Statistiken/,
  fr: /statistiques/i,
  es: /estadísticas/i,
  pl: /statystyki/i,
  pt: /estatísticas/i,
};
const PRINTING_WORD: Record<string, RegExp> = {
  en: /label printing/i,
  de: /Etikettendruck/,
  fr: /impression d'étiquettes/i,
  es: /impresión de etiquetas/i,
  pl: /druk etykiet/i,
  pt: /impressão de etiquetas/i,
};

const FOOTERS = { en, de, fr, es, pl, pt };

describe("onboarding module step footer", () => {
  for (const [language, catalogue] of Object.entries(FOOTERS)) {
    it(`${language}: names locations as always on, not the warehouse`, () => {
      const footer = catalogue.moduleChoiceFooter;
      expect(footer).toMatch(LOCATION_WORD[language]);
      expect(footer).not.toMatch(WAREHOUSE_WORD);
    });

    it(`${language}: also names statistics and label printing`, () => {
      const footer = catalogue.moduleChoiceFooter;
      expect(footer).toMatch(STATS_WORD[language]);
      expect(footer).toMatch(PRINTING_WORD[language]);
    });
  }
});
