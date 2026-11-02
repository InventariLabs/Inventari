import { describe, expect, it } from "vitest";
import { applyGrocyPreset, suggestMapping } from "./importMapping";

/** The header row `export_items_to_xlsx` writes for a priced, tracked org. */
const EXPORT_HEADERS = [
  "Name",
  "Quantity",
  "Unit",
  "Location",
  "Category",
  "Barcode",
  "Serial Number",
  "Label Code",
  "Brand",
  "Expiry Date",
  "Freeze Date",
  "Purchase price per unit (USD)",
  "Currency",
];

describe("suggestMapping", () => {
  it("maps every column of the app's own export without a click", () => {
    expect(suggestMapping(EXPORT_HEADERS)).toEqual({
      name: "Name",
      quantity: "Quantity",
      unit: "Unit",
      location: "Location",
      category: "Category",
      barcode: "Barcode",
      serial_number: "Serial Number",
      label_code: "Label Code",
      brand: "Brand",
      expiry_date: "Expiry Date",
      freeze_date: "Freeze Date",
      purchase_price: "Purchase price per unit (USD)",
    });
  });

  it("maps the location of a sheet exported before it was called Location", () => {
    // Until the rename the export headed the column "Storage". A file a user
    // kept from then has to come back into the same place, so the old header
    // still lands on the location while the export writes only the new one.
    const before = EXPORT_HEADERS.map((h) =>
      h === "Location" ? "Storage" : h,
    );
    expect(suggestMapping(before).location).toBe("Storage");
  });

  it("reads Label Code as the label code, not as a barcode", () => {
    // The update mode matches on this column; mapped onto "barcode" it would
    // have refused every round-tripped row as a duplicate instead.
    const mapping = suggestMapping(["Name", "Label Code", "Barcode"]);
    expect(mapping.label_code).toBe("Label Code");
    expect(mapping.barcode).toBe("Barcode");
  });

  it("does not mistake the price-per-unit column for the unit", () => {
    const mapping = suggestMapping(["Name", "Purchase price per unit (PLN)"]);
    expect(mapping.unit).toBe("");
    expect(mapping.purchase_price).toBe("Purchase price per unit (PLN)");
  });

  it("keeps the first header when two would feed one field", () => {
    expect(suggestMapping(["Quantity", "Quantity (old)"]).quantity).toBe(
      "Quantity",
    );
  });
});

describe("applyGrocyPreset", () => {
  it("maps Grocy's export headers over whatever was suggested", () => {
    const headers = ["name", "amount", "best_before_date", "location"];
    const mapping = applyGrocyPreset(headers, suggestMapping(headers));
    expect(mapping.quantity).toBe("amount");
    expect(mapping.expiry_date).toBe("best_before_date");
    expect(mapping.location).toBe("location");
  });
});

describe("suggestMapping by the dialog's own labels", () => {
  const PL_LABELS = {
    name: "Nazwa produktu",
    quantity: "Ilość",
    unit: "Jednostka (szt., kg, …)",
    expiry_date: "Data ważności",
    freeze_date: "Data mrożenia",
    location: "Miejsce",
    category: "Kategoria",
    brand: "Marka",
    barcode: "Kod kreskowy",
    purchase_price: "Cena zakupu za jednostkę",
    serial_number: "Numer seryjny",
    label_code: "Kod etykiety",
  };

  it("maps a Polish header row by the labels the Polish dialog shows", () => {
    const headers = [
      "Nazwa produktu",
      "Ilość",
      "Jednostka",
      "Miejsce",
      "Kod kreskowy",
      "Data ważności",
      "Data mrożenia",
      "Kategoria",
      "Marka",
      "Numer seryjny",
      "Kod etykiety",
      "Cena zakupu za jednostkę",
    ];
    expect(suggestMapping(headers, [], PL_LABELS)).toEqual({
      name: "Nazwa produktu",
      quantity: "Ilość",
      unit: "Jednostka",
      location: "Miejsce",
      barcode: "Kod kreskowy",
      expiry_date: "Data ważności",
      freeze_date: "Data mrożenia",
      category: "Kategoria",
      brand: "Marka",
      serial_number: "Numer seryjny",
      label_code: "Kod etykiety",
      purchase_price: "Cena zakupu za jednostkę",
    });
  });

  it("still reads an English header row in a Polish dialog", () => {
    const mapping = suggestMapping(["Name", "Expiry Date"], [], PL_LABELS);
    expect(mapping.name).toBe("Name");
    expect(mapping.expiry_date).toBe("Expiry Date");
  });
});
