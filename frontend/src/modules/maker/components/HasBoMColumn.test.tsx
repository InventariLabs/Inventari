import { describe, expect, it } from "vitest";
import en from "@/modules/maker/i18n/en.json";
import pl from "@/modules/maker/i18n/pl.json";
import de from "@/modules/maker/i18n/de.json";
import fr from "@/modules/maker/i18n/fr.json";
import es from "@/modules/maker/i18n/es.json";

/**
 * The column header names a property of the row; the cell answers whether the
 * row has it. Splitting the two keys was not enough — the cell still printed a
 * bare noun ("Receptura", "Formel", "Fórmula") beside a product name, which
 * reads as the row's type, and the question it raised was whether formulas had
 * been mixed into the product list. They had not: those rows were jam produced
 * by closed orders. The cell now carries an icon and an action label instead,
 * so there is no noun left in it to misread.
 */
const CATALOGS = { en, pl, de, fr, es } as const;

describe("the formula column header is not the badge text", () => {
  it.each(Object.entries(CATALOGS))(
    "%s keeps the property in the header and no naming noun in the cell",
    (_lang, catalog) => {
      const entry = (catalog as typeof en).bomEntry;
      expect(entry.columnHeader).toBeTruthy();
      expect(entry).not.toHaveProperty("badge");
      // An action, not a name: whatever the cell announces, it says what
      // pressing it does rather than what the row is.
      expect(entry.openRecipe).toBeTruthy();
      expect(entry.openRecipe.split(/\s+/).length).toBeGreaterThan(1);
    },
  );

  it.each(Object.entries(CATALOGS))(
    "%s settled on one word for the concept instead of two joined by a slash",
    (_lang, catalog) => {
      const entry = (catalog as typeof en).bomEntry;
      // "Formula / Edit BoM" and "Has formula / BoM" are an unresolved
      // glossary, not a translation.
      expect(entry.columnHeader).not.toContain("/");
      expect(entry.editRecipe).not.toContain("/");
      expect(entry.openRecipe).not.toContain("/");
    },
  );
});
