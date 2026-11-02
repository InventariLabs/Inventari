import { describe, expect, it } from "vitest";

import en from "../i18n/en.json";
import pl from "../i18n/pl.json";
import de from "../i18n/de.json";
import fr from "../i18n/fr.json";
import es from "../i18n/es.json";

/**
 * Regression guard: the page-title and navigation labels of the documents
 * pages must keep the neutral "Documents" wording. The module itself is
 * presented as "Warehouse" (documents:launcher.title) in the launcher, module
 * switcher and App Store, so a page that repeated the module's own name as its
 * heading would read as the module naming itself. This guards every consumer
 * that reads the same two keys (topbar breadcrumb, sidebar desktop nav, mobile
 * bottom bar, page h1).
 */

type Catalog = Record<string, unknown>;

const catalogs: Record<string, Catalog> = {
  en: en as unknown as Catalog,
  pl: pl as unknown as Catalog,
  de: de as unknown as Catalog,
  fr: fr as unknown as Catalog,
  es: es as unknown as Catalog,
};

const FORBIDDEN_LEGACY: Record<string, string[]> = {
  en: ["Warehouse"],
  pl: ["Magazyn"],
  de: ["Warenwirtschaft", "Lager"],
  fr: ["Entrepôt"],
  es: ["Almacén"],
};

describe("documents — sidebar/breadcrumb label guard", () => {
  for (const [lang, forbidden] of Object.entries(FORBIDDEN_LEGACY)) {
    const catalog = catalogs[lang] as Catalog;
    const title = catalog["title"] as string;
    const navDocs = ((catalog["navigation"] as Catalog) ?? {})[
      "warehouse"
    ] as string;

    it(`${lang}: documents:title must not be a legacy warehouse term`, () => {
      expect(forbidden).not.toContain(title);
    });

    it(`${lang}: documents:navigation.documents must not be a legacy warehouse term`, () => {
      expect(forbidden).not.toContain(navDocs);
    });
  }
});
