import { describe, expect, it } from "vitest";
import {
  draftProblem,
  draftTotals,
  isHeld,
  lineFromOrderLine,
  lineFromProduct,
  shortDelivery,
  toDocumentCreate,
  withImportedLines,
  withOrderLines,
  withScannedProduct,
  type ImportedLine,
  type ReceiveDraftLine,
} from "./receiveDraft";

const rice = {
  product_template_id: "tpl-rice",
  item_id: null,
  name: "Jasmine Rice",
  sku: "JR-1000",
  barcode: null,
  uom_id: "uom-pcs",
  uom_symbol: "pcs",
  is_stub: false,
};

const orderLine = {
  poId: "po-1",
  poNumber: "PO/2026/002",
  poCurrency: "PLN",
  poLineId: "pol-1",
  productTemplateId: "tpl-rice",
  name: "Jasmine Rice",
  outstanding: "40",
  ordered: "40",
  uomId: "uom-pcs",
  uomSymbol: "pcs",
  unitPrice: "6.20",
  taxRate: "23",
};

const secondOrderLine = {
  ...orderLine,
  poLineId: "pol-2",
  outstanding: "30",
  ordered: "30",
  unitPrice: "7.10",
};

function line(overrides: Partial<ReceiveDraftLine> = {}): ReceiveDraftLine {
  return { ...lineFromProduct(rice), ...overrides };
}

/** One row of a pasted delivery note. */
function pasted(overrides: Partial<ImportedLine> = {}): ImportedLine {
  return {
    id: "import-1",
    name: "Jasmine Rice",
    quantity: "1",
    product_template_id: "tpl-rice",
    item_id: null,
    uom_id: "uom-pcs",
    batch_number: null,
    expiry_date: null,
    unit_price: null,
    tax_rate: null,
    ...overrides,
  };
}

describe("receiveDraft", () => {
  it("a scanned product already on the sheet is focused, not added twice", () => {
    const existing = line();
    const result = withScannedProduct([existing], rice);

    expect(result.lines).toHaveLength(1);
    expect(result.focusKey).toBe(existing.key);
    expect(result.added).toBe(false);
  });

  it("a pasted count replaces the order's pre-filled count instead of adding to it", () => {
    const ordered = lineFromOrderLine(orderLine);
    const pasted = {
      id: "import-1",
      name: "Jasmine Rice",
      quantity: "26",
      product_template_id: "tpl-rice",
      item_id: null,
      uom_id: "uom-pcs",
      batch_number: null,
      expiry_date: null,
      unit_price: null,
      tax_rate: null,
    };

    const result = withImportedLines([ordered], [pasted]);

    expect(result.lines).toHaveLength(1);
    expect(result.lines[0].quantity).toBe("26");
    expect(result.lines[0].ordered).toBe("40");
    expect(result.lines[0].sourcePoLineId).toBe("pol-1");
    expect(result.unmatched).toEqual([]);
  });

  it("hands back a pasted row the catalogue does not know instead of dropping it", () => {
    const ghost = {
      id: "import-2",
      name: "Ghost thing",
      quantity: "3",
      product_template_id: null,
      item_id: null,
      uom_id: null,
      batch_number: null,
      expiry_date: null,
      unit_price: null,
      tax_rate: null,
    };

    const result = withImportedLines([], [ghost]);

    expect(result.lines).toEqual([]);
    expect(result.unmatched).toEqual([ghost]);
  });

  it("keeps two pasted rows of one product apart when their lots differ", () => {
    const result = withImportedLines(
      [],
      [
        pasted({
          id: "import-1",
          quantity: "2",
          batch_number: "LOT-A",
          expiry_date: "2027-01-31",
        }),
        pasted({
          id: "import-2",
          quantity: "3",
          batch_number: "LOT-B",
          expiry_date: "2027-02-28",
        }),
      ],
    );

    expect(result.lines).toHaveLength(2);
    expect(
      result.lines.map((row) => [
        row.quantity,
        row.batchNumber,
        row.expiryDate,
      ]),
    ).toEqual([
      ["2", "LOT-A", "2027-01-31"],
      ["3", "LOT-B", "2027-02-28"],
    ]);
    expect(result.unmatched).toEqual([]);
  });

  it("keeps the order line's identity when several lots arrive against it", () => {
    const result = withImportedLines(
      [lineFromOrderLine(orderLine)],
      [
        pasted({ id: "import-1", quantity: "2", batch_number: "LOT-A" }),
        pasted({ id: "import-2", quantity: "3", batch_number: "LOT-B" }),
      ],
    );

    expect(result.lines).toHaveLength(2);
    expect(result.lines[0]).toMatchObject({
      quantity: "2",
      batchNumber: "LOT-A",
      ordered: "40",
      sourcePoLineId: "pol-1",
    });
    // The second delivery row still credits the order line it arrived
    // against, but it does not claim the order's outstanding a second time.
    expect(result.lines[1]).toMatchObject({
      quantity: "3",
      batchNumber: "LOT-B",
      ordered: null,
      sourcePoLineId: "pol-1",
    });
  });

  it("replaces a re-pasted delivery row instead of adding it again", () => {
    const first = withImportedLines(
      [],
      [
        pasted({ id: "import-1", quantity: "2", batch_number: "LOT-A" }),
        pasted({ id: "import-2", quantity: "3", batch_number: "LOT-B" }),
      ],
    );
    const second = withImportedLines(first.lines, [
      pasted({ id: "import-3", quantity: "4", batch_number: "LOT-A" }),
      pasted({ id: "import-4", quantity: "5", batch_number: "LOT-B" }),
    ]);

    expect(second.lines).toHaveLength(2);
    expect(second.lines.map((row) => row.quantity)).toEqual(["4", "5"]);
  });

  it("keeps an earlier paste's lot when a later paste brings a third one", () => {
    const first = withImportedLines(
      [],
      [
        pasted({
          id: "import-1",
          quantity: "2",
          batch_number: "LOT-A",
          expiry_date: "2027-01-31",
        }),
        pasted({
          id: "import-2",
          quantity: "3",
          batch_number: "LOT-B",
          expiry_date: "2027-02-28",
        }),
      ],
    );
    const second = withImportedLines(first.lines, [
      pasted({
        id: "import-3",
        quantity: "4",
        batch_number: "LOT-C",
        expiry_date: "2027-03-31",
      }),
    ]);

    // A second paste states another delivery row, not a correction of the
    // first: the lot it names has never been on the sheet, so no existing
    // row is its landing place.
    expect(second.lines.map((row) => [row.quantity, row.batchNumber])).toEqual([
      ["2", "LOT-A"],
      ["3", "LOT-B"],
      ["4", "LOT-C"],
    ]);
  });

  it("keeps the lot an order row took when a later paste brings another one", () => {
    const first = withImportedLines(
      [lineFromOrderLine(orderLine)],
      [pasted({ id: "import-1", quantity: "2", batch_number: "LOT-A" })],
    );
    const second = withImportedLines(first.lines, [
      pasted({ id: "import-2", quantity: "3", batch_number: "LOT-B" }),
    ]);

    expect(second.lines).toHaveLength(2);
    expect(second.lines[0]).toMatchObject({
      quantity: "2",
      batchNumber: "LOT-A",
      ordered: "40",
      sourcePoLineId: "pol-1",
    });
    expect(second.lines[1]).toMatchObject({
      quantity: "3",
      batchNumber: "LOT-B",
      sourcePoLineId: "pol-1",
    });
  });

  it("lands a pasted row on a hand-typed line of its product, not beside it", () => {
    const typed = line({ quantity: "5" });
    const result = withImportedLines(
      [typed],
      [pasted({ id: "import-1", quantity: "2", batch_number: "LOT-A" })],
    );

    expect(result.lines).toHaveLength(1);
    expect(result.lines[0]).toMatchObject({
      quantity: "2",
      batchNumber: "LOT-A",
      ordered: null,
      sourcePoLineId: null,
    });
  });

  it("the order laid over typed rows keeps the count the reader already gave", () => {
    const typed = line({ quantity: "12" });
    const result = withOrderLines([typed], [orderLine]);

    expect(result).toHaveLength(1);
    expect(result[0].quantity).toBe("12");
    expect(result[0].ordered).toBe("40");
    expect(result[0].sourcePoLineId).toBe("pol-1");
    expect(result[0].unitPrice).toBe("6.20");
  });

  it("keeps one row per order line when two lines name the same product", () => {
    const result = withOrderLines([], [orderLine, secondOrderLine]);

    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({
      quantity: "40",
      ordered: "40",
      unitPrice: "6.20",
      sourcePoLineId: "pol-1",
    });
    expect(result[1]).toMatchObject({
      quantity: "30",
      ordered: "30",
      unitPrice: "7.10",
      sourcePoLineId: "pol-2",
    });
  });

  it("gives a typed row to the first order line of its product only", () => {
    const typed = line({ quantity: "12" });
    const result = withOrderLines([typed], [orderLine, secondOrderLine]);

    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({
      quantity: "12",
      ordered: "40",
      sourcePoLineId: "pol-1",
    });
    expect(result[1]).toMatchObject({
      quantity: "30",
      ordered: "30",
      sourcePoLineId: "pol-2",
    });
  });

  it("sends the order's price even while prices are hidden", () => {
    const payload = toDocumentCreate({
      docType: "IN",
      partnerId: "partner-1",
      targetLocationId: "loc-1",
      externalReference: " FV 1/10 ",
      lines: [
        lineFromOrderLine(orderLine),
        line({ key: "manual", unitPrice: "9" }),
      ],
      includePrices: false,
    });

    expect(payload.external_reference).toBe("FV 1/10");
    expect(payload.lines[0]).toMatchObject({
      product_template_id: "tpl-rice",
      expected_quantity: "40",
      source_po_line_id: "pol-1",
      unit_price: "6.20",
      tax_rate: "23",
    });
    // A hand-entered line has no agreed price, so a hidden price stays hidden.
    expect(payload.lines[1].unit_price).toBeUndefined();
  });

  it("includes a hand-entered price when accounting asked for prices", () => {
    const payload = toDocumentCreate({
      docType: "IN",
      partnerId: null,
      targetLocationId: "loc-1",
      externalReference: "",
      lines: [line({ unitPrice: "9.50", taxRate: "8" })],
      includePrices: true,
    });

    expect(payload.lines[0]).toMatchObject({
      unit_price: "9.50",
      tax_rate: "8",
    });
  });

  it("counts the lines, and the quantity only when one unit covers them all", () => {
    expect(
      draftTotals([line({ quantity: "40" }), line({ quantity: "2" })]),
    ).toEqual({ count: 2, quantity: "42", unit: "pcs" });

    expect(
      draftTotals([
        line({ quantity: "40" }),
        line({ quantity: "2", uomSymbol: "kg" }),
      ]),
    ).toEqual({ count: 2, quantity: null, unit: null });
  });

  it("names a line that arrived short, and refuses a sheet that cannot post", () => {
    const short = lineFromOrderLine(orderLine);
    short.quantity = "26";
    expect(shortDelivery([short], [orderLine]).count).toBe(1);

    expect(draftProblem([], "loc-1")).toEqual({ problem: "noLines" });
    expect(draftProblem([line()], "")).toEqual({ problem: "noWarehouse" });
    expect(
      draftProblem([line({ productTemplateId: null, itemId: null })], "loc-1"),
    ).toEqual({ problem: "noProduct" });
    expect(draftProblem([line({ quantity: "0" })], "loc-1")).toEqual({
      problem: "noQuantity",
      lineKey: expect.any(String),
    });
    expect(draftProblem([line()], "loc-1")).toBeNull();
  });

  it("counts a short order line once across the delivery rows that name it", () => {
    const rows = withImportedLines(
      [lineFromOrderLine(orderLine)],
      [
        pasted({ id: "import-1", quantity: "20", batch_number: "LOT-A" }),
        pasted({ id: "import-2", quantity: "20", batch_number: "LOT-B" }),
      ],
    ).lines;

    // Two lots, forty units: the order has nothing left to wait for.
    expect(rows).toHaveLength(2);
    expect(shortDelivery(rows, [orderLine]).count).toBe(0);

    rows[1].quantity = "19";
    expect(shortDelivery(rows, [orderLine]).count).toBe(1);
  });

  it("counts an order line the delivery leaves out as still expected", () => {
    const rows = withOrderLines([], [orderLine, secondOrderLine]);
    // The second line did not arrive, and the reader removed its row.
    const delivered = rows.filter((row) => row.sourcePoLineId === "pol-1");

    const short = shortDelivery(delivered, [orderLine, secondOrderLine]);

    // One order line the sheet no longer mentions is still owed, so the
    // delivery is not the whole order — and there is no row to mark.
    expect(short.count).toBe(1);
    expect(short.rowKeys.size).toBe(0);
  });

  it("reports the whole order only when every order line is delivered", () => {
    const rows = withOrderLines([], [orderLine, secondOrderLine]);

    const short = shortDelivery(rows, [orderLine, secondOrderLine]);

    expect(short.count).toBe(0);
    expect(short.rowKeys.size).toBe(0);
  });
  it("says which part of a row is held back and why, and nothing for a clean row", () => {
    const payload = toDocumentCreate({
      docType: "IN",
      partnerId: "partner-1",
      targetLocationId: "loc-1",
      externalReference: "",
      lines: [
        { ...lineFromOrderLine(orderLine), heldQuantity: "2" },
        line({ key: "clean" }),
      ],
      includePrices: false,
    });

    expect(payload.lines[0]).toMatchObject({
      expected_quantity: "40",
      held_quantity: "2",
      discrepancy_code: "DAMAGE",
    });
    expect(payload.lines[1].held_quantity).toBeUndefined();
    expect(payload.lines[1].discrepancy_code).toBeUndefined();
  });

  it("marks only a row nobody ordered as a typed count", () => {
    const payload = toDocumentCreate({
      docType: "IN",
      partnerId: null,
      targetLocationId: "loc-1",
      externalReference: "",
      lines: [lineFromOrderLine(orderLine), line({ key: "typed" })],
      includePrices: false,
    });

    expect(payload.lines[0].expected_is_count).toBeUndefined();
    expect(payload.lines[1].expected_is_count).toBe(true);
  });

  it("counts the held goods as delivered against the order", () => {
    const row = { ...lineFromOrderLine(orderLine), quantity: "40" };

    expect(shortDelivery([row], [orderLine]).count).toBe(0);
    expect(
      shortDelivery([{ ...row, heldQuantity: "2" }], [orderLine]).count,
    ).toBe(0);
    expect(isHeld({ ...row, heldQuantity: "0" })).toBe(false);
  });

  it("refuses more held than arrived", () => {
    expect(
      draftProblem([line({ quantity: "5", heldQuantity: "6" })], "loc-1"),
    ).toEqual({ problem: "heldAboveReceived", lineKey: expect.any(String) });
    expect(
      draftProblem([line({ quantity: "5", heldQuantity: "5" })], "loc-1"),
    ).toBeNull();
  });
});
