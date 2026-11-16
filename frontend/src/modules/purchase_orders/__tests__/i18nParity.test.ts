import { describe, expect, it } from "vitest";

import { MAINTAINED_LANGUAGES } from "@/test/languageClasses";

/**
 * Enforces key parity across the maintained languages for the
 * ``purchase_orders`` module locale catalog. Mirrors ``coreLocaleParity.test.ts`` so a missing
 * PL key is caught at test time instead of silently falling back to
 * English in production.
 */

type Catalog = Record<string, unknown>;

// Every maintained language, from the one declaration of them — a language
// added as maintained is held to parity here with no edit.
const files = import.meta.glob<{ default: Catalog }>("../i18n/*.json", {
  eager: true,
});
const catalogs: Record<string, Catalog> = Object.fromEntries(
  MAINTAINED_LANGUAGES.map((lang) => [
    lang,
    files[`../i18n/${lang}.json`].default,
  ]),
);

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

const LANGUAGES = MAINTAINED_LANGUAGES.filter((lang) => lang !== "en");

describe("purchase_orders — key parity across the maintained languages", () => {
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
