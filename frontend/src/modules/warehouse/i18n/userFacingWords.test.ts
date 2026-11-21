/**
 * Words the warehouse screens speak to a person: a document type is written
 * in words, not as its stored name, the putaway rule's first field is the
 * product, and History says what it holds and where the rest is.
 */
import { describe, expect, it } from "vitest";

import en from "./en.json";
import pl from "./pl.json";
import de from "./de.json";
import fr from "./fr.json";
import es from "./es.json";
import pt from "./pt.json";

const CATALOGUES = { en, pl, de, fr, es, pt } as const;

describe.each(Object.entries(CATALOGUES))("%s warehouse wording", (_, cat) => {
  it("does not print the stored name of the correction type", () => {
    expect(cat.corrections.warning).not.toMatch(
      /CORRECTION|KOREKTA|KORREKTUR|CORRECCIÓN|CORREÇÃO/,
    );
  });

  it("calls the putaway rule's first field the product, not a template", () => {
    expect(cat.putaway.fields.product_template).toBe(
      cat.putaway.fields.product_template_short,
    );
  });
});

describe("German picking words", () => {
  it("calls the act by one name, not picken beside kommissionieren", () => {
    // Two vocabularies for one act read as two acts: "Volle Menge picken"
    // beside "Kommissionierung" and a "Pickliste".
    const picking = JSON.stringify(de.picking);
    const templates = JSON.stringify(de.templates);
    for (const text of [picking, templates]) {
      expect(text).not.toMatch(/picken|Pickliste|Gepickt/i);
    }
    expect(de.picking.title).toBe("Kommissionierung");
  });
});

describe("History's subtitle", () => {
  it("does not claim every movement and points to Stock movements", () => {
    expect(en.history.subtitle).not.toMatch(/^Everything that moved goods\./);
    expect(en.history.subtitle).toContain("Stock movements");
  });
});
