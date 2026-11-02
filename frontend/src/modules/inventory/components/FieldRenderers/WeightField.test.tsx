import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { withLanguage } from "@/test/mocks/i18n";
import enItems from "@/i18n/locales/en/items.json";
import plItems from "@/i18n/locales/pl/items.json";
import deItems from "@/i18n/locales/de/items.json";
import frItems from "@/i18n/locales/fr/items.json";
import esItems from "@/i18n/locales/es/items.json";
import type { FieldDefinition, UomCategory } from "@/types";

const CATEGORIES: UomCategory[] = [
  {
    id: "cat-weight",
    name: "Weight",
    uoms: [
      {
        id: "uom-g",
        name: "gram",
        symbol: "g",
        factor: "1",
        rounding: "0.001",
        is_reference: true,
        is_system: false,
        category_id: "cat-weight",
      },
      {
        id: "uom-kg",
        name: "kilogram",
        symbol: "kg",
        factor: "1000",
        rounding: "0.01",
        is_reference: false,
        is_system: false,
        category_id: "cat-weight",
      },
    ],
  },
  {
    id: "cat-volume",
    name: "Volume",
    uoms: [
      {
        id: "uom-ml",
        name: "millilitre",
        symbol: "ml",
        factor: "1",
        rounding: "0.01",
        is_reference: true,
        is_system: false,
        category_id: "cat-volume",
      },
      {
        id: "uom-l",
        name: "litre",
        symbol: "l",
        factor: "1000",
        rounding: "0.01",
        is_reference: false,
        is_system: false,
        category_id: "cat-volume",
      },
    ],
  },
  {
    id: "cat-unit",
    name: "Unit",
    uoms: [
      {
        id: "uom-pcs",
        name: "piece",
        symbol: "pcs",
        factor: "1",
        rounding: "1",
        is_reference: true,
        is_system: false,
        category_id: "cat-unit",
      },
      {
        id: "uom-pack",
        name: "pack",
        symbol: "pack",
        factor: "1",
        rounding: "1",
        is_reference: false,
        is_system: false,
        category_id: "cat-unit",
      },
    ],
  },
];

vi.mock("@/modules/shared/hooks/useUoms", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/modules/shared/hooks/useUoms")>();
  return {
    ...actual,
    useUoms: () => ({ data: CATEGORIES, isLoading: false }),
  };
});

const { WeightField } = await import("./WeightField");

const field: FieldDefinition = {
  key: "weight_value",
  label: "items:weightPerPiece",
  type: "number",
  visible: true,
  required: false,
  is_system: false,
};

const noop = vi.fn();

function openPicker() {
  fireEvent.click(screen.getByRole("button", { name: /^Unit\b/ }));
}

describe("WeightField", () => {
  it.each([
    ["uom-g", "2.469 g"],
    ["uom-kg", "2.469 kg"],
  ])(
    "keeps a fractional line total in %s to the three places a quantity stores",
    async (uomId, total) => {
      await withLanguage("en", () => {
        render(
          <WeightField
            field={{ ...field, label: "items:itemWeightPerUnit" }}
            value="1.23456"
            weightUomId={uomId}
            quantity="2"
            onChange={noop}
            onUomChange={noop}
          />,
        );

        expect(
          screen.getByText(`Total for this line: ${total}`),
        ).toBeInTheDocument();
      });
    },
  );

  /**
   * The picker was locked to the Weight category, so a 1.5 l bottle had no
   * unit to be recorded in — the field's own label promises volume.
   */
  it("offers volume units, not only weight units", () => {
    render(
      <WeightField field={field} value="" onChange={noop} onUomChange={noop} />,
    );
    openPicker();

    expect(screen.getByText("ml")).toBeInTheDocument();
    expect(screen.getByText("l")).toBeInTheDocument();
    expect(screen.getByText("g")).toBeInTheDocument();
    expect(screen.getByText("kg")).toBeInTheDocument();
  });

  it("still refuses the units this field cannot mean", () => {
    render(
      <WeightField field={field} value="" onChange={noop} onUomChange={noop} />,
    );
    openPicker();

    expect(screen.queryByText("pcs")).not.toBeInTheDocument();
    expect(screen.queryByText("pack")).not.toBeInTheDocument();
  });

  /**
   * Without the symbol the line total is a bare number that reads as grams
   * whatever unit was chosen — the same guess `Item.total_weight_unit`
   * stopped making on the server side.
   */
  it("names the unit the line total is expressed in", () => {
    render(
      <WeightField
        field={field}
        value="1500"
        weightUomId="uom-ml"
        quantity="6"
        onChange={noop}
        onUomChange={noop}
      />,
    );

    expect(
      screen.getByText(/Total for this line: .*\bml\b/),
    ).toBeInTheDocument();
  });

  // The visible label lives in UnifiedFieldRenderer, across a file boundary
  // the field-names gate cannot read — the input carries its own name,
  // resolved from the same source the visible label is rendered from.
  it("names its input after the field's label", () => {
    render(
      <WeightField
        field={{ ...field, label: "items:itemWeightPerUnit" }}
        value="1500"
        onChange={noop}
        onUomChange={noop}
      />,
    );

    expect(
      screen.getByRole("spinbutton", { name: "Weight / volume per piece" }),
    ).toBeInTheDocument();
  });

  /**
   * The line total was formatted inside `toLocaleString(undefined, …)`, which
   * reads the *browser's* language: on a Polish screen it handed the shared
   * formatter a string carrying the browser's own grouping, and the formatter
   * — which only reads plain numbers — passed "9,000" through untouched.
   */
  it("writes the line total the way the interface language does", async () => {
    await withLanguage("pl", () => {
      render(
        <WeightField
          field={field}
          value="1500"
          weightUomId="uom-ml"
          quantity="6"
          onChange={noop}
          onUomChange={noop}
        />,
      );

      expect(
        screen.getByText("Łącznie w tej pozycji: 9000 ml"),
      ).toBeInTheDocument();
    });
  });

  /**
   * The hint under the field used to say "weight of one piece" while the
   * label above it offered volume — and it said so in five languages, which
   * is five places for the promise to come apart again.
   */
  it.each([
    ["en", enItems, /volume/i],
    ["pl", plItems, /objętoś/i],
    ["de", deItems, /volumen/i],
    ["fr", frItems, /volume/i],
    ["es", esItems, /volumen/i],
  ])(
    "%s tells the reader a volume belongs here too",
    (_lang, catalog, word) => {
      expect(
        (catalog as { weightPerPieceHint: string }).weightPerPieceHint,
      ).toMatch(word);
    },
  );
});
