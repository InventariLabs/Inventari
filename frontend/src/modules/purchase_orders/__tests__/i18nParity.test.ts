import { describe, expect, it } from "vitest";

import en from "../i18n/en.json";
import pl from "../i18n/pl.json";
import de from "../i18n/de.json";
import fr from "../i18n/fr.json";
import es from "../i18n/es.json";

/**
 * Enforces 5-language key parity for the ``purchase_orders`` module
 * locale catalog. Mirrors ``coreLocaleParity.test.ts`` so a missing
 * PL key is caught at test time instead of silently falling back to
 * English in production.
 */

type Catalog = Record<string, unknown>;

const catalogs: Record<string, Catalog> = {
  en: en as unknown as Catalog,
  pl: pl as unknown as Catalog,
  de: de as unknown as Catalog,
  fr: fr as unknown as Catalog,
  es: es as unknown as Catalog,
};

function flatKeys(node: unknown, prefix: string[] = []): string[] {
  if (node == null) return [];
  if (typeof node === "string") return [prefix.join(".")];
  if (Array.isArray(node)) {
    return node.flatMap((v, i) => flatKeys(v, [...prefix, String(i)]));
  }
  if (typeof node === "object") {
    return Object.entries(node as Catalog).flatMap(([k, v]) =>
      flatKeys(v, [...prefix, k]),
    );
  }
  return [];
}

const LANGUAGES = ["pl", "de", "fr", "es"] as const;

describe("purchase_orders — 5-language key parity", () => {
  const enKeys = new Set(flatKeys(catalogs.en));

  for (const lang of LANGUAGES) {
    const otherKeys = new Set(flatKeys(catalogs[lang]));
    const missing = [...enKeys].filter((k) => !otherKeys.has(k));
    const extra = [...otherKeys].filter((k) => !enKeys.has(k));

    it(`${lang} has no keys missing vs en`, () => {
      expect(missing).toEqual([]);
    });

    if (lang !== "pl") {
      it(`${lang} has no keys extra vs en`, () => {
        expect(extra).toEqual([]);
      });
    }
  }
});
