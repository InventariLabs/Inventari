import { describe, expect, it } from "vitest";
import {
  boundsFindings,
  ceilingSentenceFindings,
  expectedBounds,
  parseBackendQuantity,
  parseTsConstant,
  zeroRefusalFindings,
} from "./check-quantity-bounds.mjs";

describe("check-quantity-bounds", () => {
  it("reads the shape the backend declares", () => {
    const backend = parseBackendQuantity(
      "QUANTITY_MAX_DIGITS = 12\nQUANTITY_SCALE = 3\n",
    );

    expect(backend).toEqual({ maxDigits: 12, scale: 3 });
    expect(expectedBounds(backend)).toEqual({
      max: 999999999.999,
      step: 0.001,
    });
  });

  it("reads a TypeScript constant through its underscores", () => {
    const text = "export const QUANTITY_MAX = 999_999_999.999;";

    expect(parseTsConstant(text, "QUANTITY_MAX")).toBe(999999999.999);
    expect(parseTsConstant(text, "QUANTITY_STEP")).toBeNull();
  });

  describe("the guards", () => {
    const backend = { maxDigits: 12, scale: 3 };

    it("stays quiet when both sides agree", () => {
      expect(boundsFindings(backend, 999999999.999, 0.001)).toEqual([]);
    });

    it("names the max when the backend's shape moved", () => {
      const findings = boundsFindings(
        { maxDigits: 13, scale: 3 },
        999999999.999,
        0.001,
      );

      expect(findings).toHaveLength(1);
      expect(findings[0]).toContain("QUANTITY_MAX is 999999999.999");
      expect(findings[0]).toContain("9999999999.999");
    });

    it("names the step when the backend's scale moved", () => {
      const findings = boundsFindings(
        { maxDigits: 12, scale: 4 },
        999999999.999,
        0.001,
      );

      // A scale change moves the derived ceiling too, so both mirrors are
      // named — the step is the one the form's floor reads.
      expect(findings).toHaveLength(2);
      const step = findings.find((f) => f.includes("QUANTITY_STEP"));
      expect(step).toContain("QUANTITY_STEP is 0.001");
      expect(step).toContain("0.0001");
    });
  });

  describe("the ceiling sentence", () => {
    const catalog = (value) => [
      {
        path: "pl.json",
        text: JSON.stringify({
          addItem: { validation: { quantityMax: value } },
        }),
      },
    ];

    it("accepts a sentence that interpolates the value", () => {
      expect(
        ceilingSentenceFindings(
          catalog("Ilość powyżej {{max}} nie może zostać zapisana"),
        ),
      ).toEqual([]);
    });

    it("refuses a sentence that repeats the value", () => {
      const findings = ceilingSentenceFindings(
        catalog("Ilość powyżej 999999999.999 nie może zostać zapisana"),
      );

      expect(findings).toHaveLength(1);
      expect(findings[0]).toContain("does not interpolate {{max}}");
    });

    it("refuses a pasted number standing beside the interpolation", () => {
      const findings = ceilingSentenceFindings(
        catalog(
          "Ilość powyżej {{max}} (999999999.999) nie może zostać zapisana",
        ),
      );

      expect(findings).toHaveLength(1);
      expect(findings[0]).toContain("pasted number");
    });
  });

  describe("the zero refusal", () => {
    const key = "shopping_list_item_quantity_rounds_to_zero";
    const catalog = (...sentences) => [
      {
        path: "_errors_xx.py",
        text: sentences
          .map((sentence) => `    '${key}': ${sentence},`)
          .join("\n"),
      },
    ];

    it("accepts a sentence that interpolates the step", () => {
      expect(zeroRefusalFindings(catalog("'Smallest is {smallest}'"))).toEqual(
        [],
      );
    });

    it("refuses a sentence that repeats the step", () => {
      const findings = zeroRefusalFindings(catalog("'Smallest is 0.001'"));

      expect(findings).toHaveLength(1);
      expect(findings[0]).toContain("does not interpolate {smallest}");
    });

    it("checks every line a file holds the key on", () => {
      const findings = zeroRefusalFindings(
        catalog("'Smallest is {smallest}'", "'Najmniejsza to 0,001'"),
      );

      expect(findings).toHaveLength(1);
    });

    it("refuses a catalogue that lost the key", () => {
      const findings = zeroRefusalFindings([
        { path: "_errors_xx.py", text: "ERRORS = {}" },
      ]);

      expect(findings[0]).toContain(
        "no shopping_list_item_quantity_rounds_to_zero",
      );
    });
  });
});
