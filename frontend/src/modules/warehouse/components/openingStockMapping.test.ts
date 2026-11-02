import { describe, expect, it } from "vitest";
import { suggestOpeningStockMapping } from "./openingStockMapping";

describe("suggestOpeningStockMapping", () => {
  it("reads a Polish stock sheet without a click per column", () => {
    expect(
      suggestOpeningStockMapping([
        "Produkt",
        "Indeks",
        "Kod kreskowy",
        "Stan",
        "Jm",
        "Cena zakupu",
        "Partia",
        "Data ważności",
      ]),
    ).toEqual({
      name: "Produkt",
      sku: "Indeks",
      barcode: "Kod kreskowy",
      quantity: "Stan",
      uom_symbol: "Jm",
      unit_price: "Cena zakupu",
      batch_number: "Partia",
      expiry_date: "Data ważności",
    });
  });

  it("tells a barcode column from a product code column", () => {
    const mapping = suggestOpeningStockMapping(["Name", "Code", "EAN", "Qty"]);
    expect(mapping).toMatchObject({
      name: "Name",
      sku: "Code",
      barcode: "EAN",
      quantity: "Qty",
    });
  });
});
