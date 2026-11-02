/*
 * Equipment i18n parity: restore-dialog copy, checkout-modal placeholders
 * and the models empty-state hint, present and honest in all 5 languages.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

import en from "../i18n/en.json";
import pl from "../i18n/pl.json";
import de from "../i18n/de.json";
import fr from "../i18n/fr.json";
import es from "../i18n/es.json";

type Catalog = Record<string, unknown>;

const catalogs: Record<string, Catalog> = {
  en: en as unknown as Catalog,
  pl: pl as unknown as Catalog,
  de: de as unknown as Catalog,
  fr: fr as unknown as Catalog,
  es: es as unknown as Catalog,
};

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

describe("equipment i18n keys (parity across 5 languages)", () => {
  it.each(Object.entries(catalogs))(
    "%s has detail.confirm_restore_msg",
    (_lang, catalog) => {
      const v = pathGet(catalog, "detail.confirm_restore_msg");
      expect(typeof v).toBe("string");
      expect(String(v).trim().length).toBeGreaterThan(0);
    },
  );

  it.each(Object.entries(catalogs))(
    "%s has assignments.checkout_modal.placeholders.{name,email}",
    (_lang, catalog) => {
      const name = pathGet(
        catalog,
        "assignments.checkout_modal.placeholders.name",
      );
      const email = pathGet(
        catalog,
        "assignments.checkout_modal.placeholders.email",
      );
      expect(typeof name).toBe("string");
      expect((name as string).length).toBeGreaterThan(0);
      expect(typeof email).toBe("string");
      expect((email as string).length).toBeGreaterThan(0);
    },
  );

  it.each(Object.entries(catalogs))(
    "%s models.empty_hint no longer promises Save-as-model action",
    (_lang, catalog) => {
      const hint = String(
        pathGet(catalog, "models.empty_hint") ?? "",
      ).toLowerCase();
      // The empty state must not advertise a non-existent action.
      expect(hint).not.toMatch(/save as model/);
      expect(hint).not.toMatch(/save_as_model/);
      expect(hint).not.toMatch(/zapisz jako model/);
      expect(hint).not.toMatch(/als modell speichern/);
      expect(hint).not.toMatch(/guardar como modelo/);
      expect(hint).not.toMatch(/enregistrer comme modèle/);
    },
  );

  it("i18n catalogs are valid JSON files on disk", () => {
    const dir = path.resolve(__dirname, "../i18n");
    for (const lang of Object.keys(catalogs)) {
      const raw = fs.readFileSync(path.join(dir, `${lang}.json`), "utf-8");
      expect(() => JSON.parse(raw)).not.toThrow();
    }
  });
});
