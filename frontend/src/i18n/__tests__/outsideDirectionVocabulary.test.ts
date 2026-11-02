/**
 * The world outside the organisation is named after the end of the arrow it
 * stands on.
 *
 * One key used to fill both ends, and every translation but English phrased
 * it as the source: "z zewnątrz", "desde fuera", "von außen", "de
 * l'extérieur". On an issue row that read as the goods arriving from outside
 * on their way out — an issue never arrives from anywhere; it leaves. Two
 * ends, two words, the same source/target split UI_GUIDELINES §14.2 guards
 * for named locations.
 */
import { describe, expect, it } from "vitest";

import inventoryEn from "@/modules/inventory/i18n/en.json";
import inventoryPl from "@/modules/inventory/i18n/pl.json";
import inventoryDe from "@/modules/inventory/i18n/de.json";
import inventoryFr from "@/modules/inventory/i18n/fr.json";
import inventoryEs from "@/modules/inventory/i18n/es.json";

const CATALOGUES = {
  en: inventoryEn,
  pl: inventoryPl,
  de: inventoryDe,
  fr: inventoryFr,
  es: inventoryEs,
};

/** English "outside" faces both ways; the others decline by direction. */
const DIRECTION_NEUTRAL = ["en"];

describe("the placeholder for a location the ledger does not name", () => {
  for (const [lang, cat] of Object.entries(CATALOGUES)) {
    const moves = (cat as { moves: Record<string, unknown> }).moves;

    it(`names the end goods come in by and the end they leave by (${lang})`, () => {
      expect(typeof moves.outsideFrom).toBe("string");
      expect(typeof moves.outsideTo).toBe("string");
    });

    if (!DIRECTION_NEUTRAL.includes(lang)) {
      it(`declines the two ends differently (${lang})`, () => {
        expect(moves.outsideFrom).not.toBe(moves.outsideTo);
      });
    }

    it(`keeps no single word for both ends (${lang})`, () => {
      expect(moves.outside).toBeUndefined();
    });
  }
});
