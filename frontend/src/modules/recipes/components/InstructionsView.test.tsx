import { describe, expect, it } from "vitest";
import { parseInstructions } from "./InstructionsView";

describe("parseInstructions across the five shipped languages", () => {
  // The recipe's language has nothing to do with the interface language: the
  // text is whatever the author typed. Matching only Polish and English left
  // German, French and Spanish recipes rendering as one undifferentiated block.
  it.each([
    ["pl", "Krok 1: Zagotuj wodę"],
    ["en", "Step 1: Boil water"],
    ["de", "Schritt 1: Wasser kochen"],
    ["fr", "Étape 1 : Faire bouillir l'eau"],
    ["es", "Paso 1: Hervir el agua"],
  ])("recognises a numbered step in %s", (_lang, text) => {
    const [block] = parseInstructions(text);
    expect(block.type).toBe("step");
    expect(block.stepNumber).toBe(1);
  });

  it.each([
    ["pl", "Wskazówka: użyj zimnej wody"],
    ["en", "Tip: use cold water"],
    ["de", "Tipp: kaltes Wasser verwenden"],
    ["fr", "Conseil : utilisez de l'eau froide"],
    ["es", "Consejo: usa agua fría"],
  ])("recognises a tip in %s", (_lang, text) => {
    const [block] = parseInstructions(text);
    expect(block.type).toBe("tip");
  });

  it("leaves ordinary prose alone", () => {
    const [block] = parseInstructions("Stir until the sauce thickens.");
    expect(block.type).toBe("text");
  });
});
