import { describe, expect, it } from "vitest";
import { suggestMapping } from "./importMapping";

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
  "SKU",
  "Stock alert",
  "Description",
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
      sku: "SKU",
      min_quantity: "Stock alert",
      description: "Description",
      sublocation: "",
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
      sublocation: "",
      sku: "",
      description: "",
      min_quantity: "",
    });
  });

  it("still reads an English header row in a Polish dialog", () => {
    const mapping = suggestMapping(["Name", "Expiry Date"], [], PL_LABELS);
    expect(mapping.name).toBe("Name");
    expect(mapping.expiry_date).toBe("Expiry Date");
  });
});

/** The header row of each tool's export, and the columns it should feed.
 *  The backend's import test runs each mapping over a row of that shape. */
describe("suggestMapping for another tool's export", () => {
  const suggested = (headers: string[]) =>
    Object.fromEntries(
      Object.entries(suggestMapping(headers)).filter(([, column]) => column),
    );

  it("reads Odoo's product export", () => {
    expect(
      suggested([
        "Name",
        "Internal Reference",
        "Barcode",
        "Sales Price",
        "Cost",
        "Product Category",
        "Unit of Measure",
        "Quantity On Hand",
      ]),
    ).toEqual({
      name: "Name",
      sku: "Internal Reference",
      barcode: "Barcode",
      purchase_price: "Cost",
      category: "Product Category",
      unit: "Unit of Measure",
      quantity: "Quantity On Hand",
    });
  });

  it("reads Odoo's stock export, on hand rather than reserved", () => {
    expect(
      suggested([
        "Location",
        "Product",
        "Product Category",
        "Lot/Serial Number",
        "Package",
        "Owner",
        "Reserved Quantity",
        "On Hand Quantity",
        "Unit of Measure",
      ]),
    ).toEqual({
      location: "Location",
      name: "Product",
      category: "Product Category",
      quantity: "On Hand Quantity",
      unit: "Unit of Measure",
    });
  });

  it("reads Sortly, where the only price is the item's", () => {
    expect(
      suggested([
        "Entry Name",
        "Entry Type",
        "Folder Path",
        "Quantity",
        "Unit",
        "Min Level",
        "Price",
        "Tags",
        "Notes",
        "Barcode/QR-1",
      ]),
    ).toEqual({
      name: "Entry Name",
      location: "Folder Path",
      quantity: "Quantity",
      unit: "Unit",
      min_quantity: "Min Level",
      purchase_price: "Price",
      description: "Notes",
      barcode: "Barcode/QR-1",
    });
  });

  it("reads inFlow's stock levels, a location over two columns", () => {
    expect(
      suggested([
        "ProductName",
        "SKU",
        "Location",
        "Sublocation",
        "Quantity",
        "Serial",
        "LotNumber",
        "ExpiryDate",
      ]),
    ).toEqual({
      name: "ProductName",
      sku: "SKU",
      location: "Location",
      sublocation: "Sublocation",
      quantity: "Quantity",
      serial_number: "Serial",
      expiry_date: "ExpiryDate",
    });
  });

  it("reads inFlow's product file, the cost rather than the price", () => {
    expect(
      suggested([
        "ProductName",
        "SKU",
        "Barcode",
        "Category",
        "Description",
        "UnitPrice",
        "Cost",
        "UnitOfMeasure",
      ]),
    ).toEqual({
      name: "ProductName",
      sku: "SKU",
      barcode: "Barcode",
      category: "Category",
      description: "Description",
      purchase_price: "Cost",
      unit: "UnitOfMeasure",
    });
  });

  it("reads Zoho's items, the purchase rate rather than the selling one", () => {
    expect(
      suggested([
        "Item Name",
        "SKU",
        "EAN",
        "Description",
        "Usage unit",
        "Rate",
        "Purchase Rate",
        "Reorder Level",
        "Category Name",
        "Warehouse Name",
        "Stock On Hand",
      ]),
    ).toEqual({
      name: "Item Name",
      sku: "SKU",
      barcode: "EAN",
      description: "Description",
      unit: "Usage unit",
      purchase_price: "Purchase Rate",
      min_quantity: "Reorder Level",
      category: "Category Name",
      location: "Warehouse Name",
      quantity: "Stock On Hand",
    });
  });

  it("reads Katana's product and material files", () => {
    expect(
      suggested([
        "Material name",
        "Variant code / SKU",
        "Category",
        "Unit of measure",
        "Default purchase price",
      ]),
    ).toEqual({
      name: "Material name",
      sku: "Variant code / SKU",
      category: "Category",
      unit: "Unit of measure",
      purchase_price: "Default purchase price",
    });
    expect(suggested(["Product name / Material name"]).name).toBe(
      "Product name / Material name",
    );
  });

  it("reads BoxHero's quantity column per location, Cost before Price", () => {
    expect(
      suggested([
        "SKU",
        "Item Name",
        "Barcode",
        "Cost",
        "Price",
        "Brand",
        "Category",
        "Qty(Warehouse)",
        "Qty(Shop)",
      ]),
    ).toEqual({
      sku: "SKU",
      name: "Item Name",
      barcode: "Barcode",
      purchase_price: "Cost",
      brand: "Brand",
      category: "Category",
      "stock_at:Warehouse": "Qty(Warehouse)",
      "stock_at:Shop": "Qty(Shop)",
    });
  });

  it("reads Homebox's export", () => {
    expect(
      suggested([
        "HB.name",
        "HB.description",
        "HB.notes",
        "HB.location",
        "HB.tags",
        "HB.quantity",
        "HB.manufacturer",
        "HB.serial_number",
        "HB.purchase_price",
        "HB.purchase_date",
        "HB.warranty_expires",
      ]),
    ).toEqual({
      name: "HB.name",
      description: "HB.description",
      location: "HB.location",
      quantity: "HB.quantity",
      brand: "HB.manufacturer",
      serial_number: "HB.serial_number",
      purchase_price: "HB.purchase_price",
    });
  });
});
