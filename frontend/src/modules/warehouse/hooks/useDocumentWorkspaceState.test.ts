import { describe, expect, it } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDocumentWorkspaceState } from "./useDocumentWorkspaceState";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { documentLine, warehouseDocument } from "@/test/factories/documents";

function makeDoc(overrides?: Partial<WarehouseDocument>): WarehouseDocument {
  return warehouseDocument({
    id: "doc-1",
    organization_id: "org-1",
    type: "IN",
    number: "IN/2026/001",
    status: "DRAFT",
    partner_id: null,
    source_location_id: null,
    target_location_id: null,
    scheduled_date: null,
    notes: null,
    external_reference: null,
    lines: [],
    created_by: "user-1",
    confirmed_by: null,
    confirmed_at: null,
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-01-01T00:00:00",
    completed_at: null,
    ...overrides,
  });
}

describe("useDocumentWorkspaceState", () => {
  it("defaults to IN type with one empty line when no document", () => {
    const { result } = renderHook(() => useDocumentWorkspaceState({}));
    expect(result.current.docType).toBe("IN");
    expect(result.current.lines).toHaveLength(1);
    expect(result.current.lines[0].name).toBe("");
    expect(result.current.lines[0].quantity).toBe(1);
  });

  it("uses document type when document is provided", () => {
    const doc = makeDoc({ type: "OUT" });
    const { result } = renderHook(() =>
      useDocumentWorkspaceState({ document: doc }),
    );
    expect(result.current.docType).toBe("OUT");
    expect(result.current.isEdit).toBe(true);
  });

  it("uses initialType when no document", () => {
    const { result } = renderHook(() =>
      useDocumentWorkspaceState({ initialType: "INT" }),
    );
    expect(result.current.docType).toBe("INT");
  });

  it("maps existing document lines to ReceiptLines", () => {
    const doc = makeDoc({
      lines: [
        documentLine({
          id: "line-1",
          document_id: "doc-1",
          line_number: 1,
          item_id: "item-1",
          product_template_id: "pt-1",
          name: "Widget",
          brand: "ACME",
          barcode: "123",
          sku: "SKU-1",
          quantity: "5",
          uom_id: "uom-1",
          batch_number: "B1",
          expiry_date: "2026-12-31",
          notes: "handle carefully",
          unit_price: "10.00",
          tax_rate: "23",
          serial_number: null,
        }),
      ],
    });
    const { result } = renderHook(() =>
      useDocumentWorkspaceState({ document: doc }),
    );
    expect(result.current.lines).toHaveLength(1);
    expect(result.current.lines[0].name).toBe("Widget");
    expect(result.current.lines[0].item_id).toBe("item-1");
    expect(result.current.lines[0].quantity).toBe(5);
    expect(result.current.lines[0].batch_number).toBe("B1");
    expect(result.current.lines[0].unit_price).toBe("10.00");
  });

  describe("requiresSource / requiresTarget / requiresPartner", () => {
    it("IN requires target and partner only", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "IN" }),
      );
      expect(result.current.requiresSource).toBe(false);
      expect(result.current.requiresTarget).toBe(true);
      expect(result.current.requiresPartner).toBe(true);
    });

    it("OUT requires source and partner only", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "OUT" }),
      );
      expect(result.current.requiresSource).toBe(true);
      expect(result.current.requiresTarget).toBe(false);
      expect(result.current.requiresPartner).toBe(true);
    });

    it("INT requires source and target, no partner", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "INT" }),
      );
      expect(result.current.requiresSource).toBe(true);
      expect(result.current.requiresTarget).toBe(true);
      expect(result.current.requiresPartner).toBe(false);
    });

    it("PW requires target only", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "INTERNAL_IN" }),
      );
      expect(result.current.requiresSource).toBe(false);
      expect(result.current.requiresTarget).toBe(true);
      expect(result.current.requiresPartner).toBe(false);
    });

    it("RW requires source only", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "INTERNAL_OUT" }),
      );
      expect(result.current.requiresSource).toBe(true);
      expect(result.current.requiresTarget).toBe(false);
      expect(result.current.requiresPartner).toBe(false);
    });
  });

  describe("line operations", () => {
    it("appendLine adds a line after one the person has started", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() => result.current.updateLine(0, { name: "First" }));
      act(() =>
        result.current.appendLine({
          _key: "k1",
          name: "New Item",
          quantity: 3,
          batch_number: "",
          expiry_date: "",
          notes: "",
        }),
      );
      expect(result.current.lines).toHaveLength(2);
      expect(result.current.lines[1].name).toBe("New Item");
    });

    it("addEmptyLine adds a blank line", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() => result.current.addEmptyLine());
      expect(result.current.lines).toHaveLength(2);
    });

    it("removeLine removes by index", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() => result.current.updateLine(0, { name: "First" }));
      act(() =>
        result.current.appendLine({
          _key: "k1",
          name: "Second",
          quantity: 1,
          batch_number: "",
          expiry_date: "",
          notes: "",
        }),
      );
      expect(result.current.lines).toHaveLength(2);
      act(() => result.current.removeLine(0));
      expect(result.current.lines).toHaveLength(1);
      expect(result.current.lines[0].name).toBe("Second");
    });

    it("updateLine patches a line by index", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() => result.current.updateLine(0, { name: "Updated", quantity: 5 }));
      expect(result.current.lines[0].name).toBe("Updated");
      expect(result.current.lines[0].quantity).toBe(5);
    });

    it("addOrIncrementLine increments existing line by item_id", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() =>
        result.current.updateLine(0, { item_id: "item-1", quantity: 2 }),
      );
      act(() =>
        result.current.addOrIncrementLine({
          _key: "k1",
          name: "Widget",
          item_id: "item-1",
          quantity: 3,
          batch_number: "",
          expiry_date: "",
          notes: "",
        }),
      );
      expect(result.current.lines).toHaveLength(1);
      expect(result.current.lines[0].quantity).toBe(5);
    });

    it("addOrIncrementLine appends new line when no match", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() =>
        result.current.updateLine(0, { item_id: "item-1", quantity: 1 }),
      );
      act(() =>
        result.current.addOrIncrementLine({
          _key: "k1",
          name: "Other",
          item_id: "item-2",
          quantity: 1,
          batch_number: "",
          expiry_date: "",
          notes: "",
        }),
      );
      expect(result.current.lines).toHaveLength(2);
    });
  });

  describe("consolidateLines", () => {
    it("merges duplicate lines with same item_id", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() =>
        result.current.updateLine(0, {
          item_id: "item-1",
          quantity: 3,
          name: "Widget",
        }),
      );
      act(() =>
        result.current.appendLine({
          _key: "k2",
          item_id: "item-1",
          name: "Widget",
          quantity: 2,
          batch_number: "",
          expiry_date: "",
          notes: "",
          unit_price: "",
          tax_rate: "",
          uom_id: null,
        }),
      );
      expect(result.current.lines).toHaveLength(2);
      act(() => result.current.consolidateLines());
      expect(result.current.lines).toHaveLength(1);
      expect(result.current.lines[0].quantity).toBe(5);
    });

    it("does not merge lines with different batch numbers", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() =>
        result.current.updateLine(0, {
          item_id: "item-1",
          quantity: 3,
          name: "Widget",
          batch_number: "B1",
        }),
      );
      act(() =>
        result.current.appendLine({
          _key: "k2",
          item_id: "item-1",
          name: "Widget",
          quantity: 2,
          batch_number: "B2",
          expiry_date: "",
          notes: "",
        }),
      );
      act(() => result.current.consolidateLines());
      expect(result.current.lines).toHaveLength(2);
    });

    it("does not merge lines that carry different fields of another module", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() =>
        result.current.updateLine(0, {
          item_id: "item-1",
          quantity: 3,
          name: "Widget",
          meta_data: { lot_certificates: { number: "C-1" } },
        }),
      );
      act(() =>
        result.current.appendLine({
          _key: "k2",
          item_id: "item-1",
          name: "Widget",
          quantity: 2,
          batch_number: "",
          expiry_date: "",
          notes: "",
          meta_data: { lot_certificates: { number: "C-2" } },
        }),
      );
      act(() => result.current.consolidateLines());
      expect(result.current.lines).toHaveLength(2);
    });
  });

  describe("other modules' fields", () => {
    it("keeps what each module writes, and sends it with the document", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      const key = result.current.lines[0]._key;
      act(() => result.current.updateLine(0, { name: "Widget" }));
      // Two modules writing in one go: neither loses the other's key.
      act(() => {
        result.current.setLineMetaData(key, "lot_certificates", {
          number: "C-1",
        });
        result.current.setLineMetaData(key, "grading", { grade: "A" });
        result.current.setMetaData("customs", { entry: "PL-77" });
      });

      const payload = result.current.toCreatePayload();

      expect(payload.meta_data).toEqual({ customs: { entry: "PL-77" } });
      expect(payload.lines[0].meta_data).toEqual({
        lot_certificates: { number: "C-1" },
        grading: { grade: "A" },
      });

      act(() => result.current.setLineMetaData(key, "grading", null));
      expect(result.current.toCreatePayload().lines[0].meta_data).toEqual({
        lot_certificates: { number: "C-1" },
      });
    });

    it("sends no fields at all on a new document nobody wrote any on", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() => result.current.updateLine(0, { name: "Widget" }));

      const payload = result.current.toCreatePayload();

      expect(payload.meta_data).toBeUndefined();
      expect(payload.lines[0].meta_data).toBeUndefined();
    });

    it("starts an edit from the fields the document has", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({
          document: makeDoc({
            meta_data: { customs: { entry: "PL-77" } },
            lines: [
              documentLine({
                name: "Widget",
                quantity: "2",
                meta_data: { grading: { grade: "A" } },
              }),
            ],
          }),
        }),
      );

      const payload = result.current.toUpdatePayload();

      expect(payload.meta_data).toEqual({ customs: { entry: "PL-77" } });
      expect(payload.lines?.[0].meta_data).toEqual({ grading: { grade: "A" } });
    });
  });

  describe("toCreatePayload", () => {
    it("builds correct payload", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() => result.current.setPartnerId("partner-1"));
      act(() => result.current.setTargetLocationId("loc-1"));
      act(() => result.current.setNotes("test notes"));
      act(() => result.current.updateLine(0, { name: "Widget", quantity: 2 }));
      const payload = result.current.toCreatePayload();
      expect(payload.type).toBe("IN");
      expect(payload.partner_id).toBe("partner-1");
      expect(payload.target_location_id).toBe("loc-1");
      expect(payload.notes).toBe("test notes");
      expect(payload.lines).toHaveLength(1);
      expect(payload.lines[0].name).toBe("Widget");
      expect(payload.lines[0].expected_quantity).toBe(2);
    });

    it("carries product_template_id and serial_number into the payload", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() =>
        result.current.updateLine(0, {
          name: "Widget",
          product_template_id: "pt-1",
          serial_number: "SN-42",
          quantity: 3,
        }),
      );
      const payload = result.current.toCreatePayload();
      expect(payload.lines[0].product_template_id).toBe("pt-1");
      expect(payload.lines[0].serial_number).toBe("SN-42");
    });

    it("sends expected_quantity on a line", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      act(() => result.current.updateLine(0, { name: "Widget", quantity: 3 }));
      const payload = result.current.toCreatePayload();
      expect(payload.lines[0].expected_quantity).toBe(3);
    });

    it("omits empty strings as undefined", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      const payload = result.current.toCreatePayload();
      expect(payload.partner_id).toBeUndefined();
      expect(payload.scheduled_date).toBeUndefined();
      expect(payload.notes).toBeUndefined();
    });
  });

  describe("validateForm (aggregate)", () => {
    it("includes partnerRequired when IN without partner", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "IN" }),
      );
      expect(result.current.validateForm()).toHaveProperty(
        "partner_id",
        "errors.partnerRequired",
      );
    });

    // The picker lists only the partners the document's role set and the
    // active flag let through. A partner_id pointing outside that list — a
    // supplier created from a dispatch's recipient field, a partner
    // deactivated after the document was drafted — sits beneath a field
    // that shows its placeholder, and the form has to call that field
    // empty, the way the reader sees it.
    it("reports the partner field as empty when its value is not among the offered partners", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "IN" }),
      );
      act(() => result.current.setPartnerId("partner-gone"));
      expect(result.current.validateForm(false)).toHaveProperty(
        "partner_id",
        "errors.partnerRequired",
      );
    });

    it("accepts a partner the picker can offer, and one it has not decided on yet", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "IN" }),
      );
      act(() => result.current.setPartnerId("partner-1"));
      expect(result.current.validateForm(true)).not.toHaveProperty(
        "partner_id",
      );
      expect(result.current.validateForm(undefined)).not.toHaveProperty(
        "partner_id",
      );
    });

    it("includes sourceLocationRequired when OUT without source", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "OUT" }),
      );
      act(() => result.current.setPartnerId("p1"));
      expect(result.current.validateForm()).toHaveProperty(
        "source_location_id",
        "errors.sourceLocationRequired",
      );
    });

    it("includes targetLocationRequired when IN without target", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "IN" }),
      );
      act(() => result.current.setPartnerId("p1"));
      expect(result.current.validateForm()).toHaveProperty(
        "target_location_id",
        "errors.targetLocationRequired",
      );
    });

    it("includes lineNameRequired when line has no name or item_id", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "IN" }),
      );
      act(() => result.current.setPartnerId("p1"));
      act(() => result.current.setTargetLocationId("l1"));
      const errs = result.current.validateForm();
      // Aggregate: also no source for IN, but source is not required → only line.
      expect(Object.values(errs)).toContain("errors.lineNameRequired");
    });

    it("returns an empty object when all required fields are filled", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "IN" }),
      );
      act(() => result.current.setPartnerId("p1"));
      act(() => result.current.setTargetLocationId("l1"));
      act(() =>
        result.current.updateLine(0, { name: "Widget", item_id: "item-1" }),
      );
      expect(result.current.validateForm()).toEqual({});
    });

    it("includes itemIdRequiredForDispatch when OUT line has no item_id", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "OUT" }),
      );
      act(() => result.current.setPartnerId("p1"));
      act(() => result.current.setSourceLocationId("l1"));
      act(() => result.current.updateLine(0, { name: "Widget" }));
      const errs = result.current.validateForm();
      // item_id error is keyed by line._key, not a fixed name.
      const lineKey = result.current.lines[0]._key;
      expect(errs).toHaveProperty(
        `line.${lineKey}.item_id`,
        "errors.itemIdRequiredForDispatch",
      );
    });

    // Everything that takes goods off a shelf. The transfer and the scrap
    // were missing: their lines went out naming a catalogue entry, and the
    // executors could do nothing with it — the transfer refused at its last
    // step, the scrap quietly moved nothing and closed as done. Mirrors
    // `requires_stock_row` in document_types.py.
    it.each([
      ["OUT", true],
      ["INTERNAL_OUT", true],
      ["INT", true],
      ["SCRAP", true],
      ["IN", false],
      ["INTERNAL_IN", false],
    ] as const)(
      "line of a %s document needs a record: %s",
      (type, needsRecord) => {
        const { result } = renderHook(() =>
          useDocumentWorkspaceState({ initialType: type }),
        );
        act(() => result.current.setPartnerId("p1"));
        act(() => result.current.setSourceLocationId("l1"));
        act(() => result.current.setTargetLocationId("l2"));
        act(() => result.current.updateLine(0, { name: "Widget" }));
        const lineKey = result.current.lines[0]._key;
        const errs = result.current.validateForm();
        if (needsRecord) {
          expect(errs[`line.${lineKey}.item_id`]).toBe(
            "errors.itemIdRequiredForDispatch",
          );
        } else {
          expect(errs).not.toHaveProperty(`line.${lineKey}.item_id`);
        }
      },
    );

    it("returns ALL applicable errors at once (full list)", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "IN" }),
      );
      // No partner, no target, line has no name and no item_id.
      const errs = result.current.validateForm();
      const lineKey = result.current.lines[0]._key;
      expect(errs).toHaveProperty("partner_id", "errors.partnerRequired");
      expect(errs).toHaveProperty(
        "target_location_id",
        "errors.targetLocationRequired",
      );
      expect(errs).toHaveProperty(
        `line.${lineKey}.name`,
        "errors.lineNameRequired",
      );
    });
  });

  describe("hasLines", () => {
    it("is true when lines exist", () => {
      const { result } = renderHook(() => useDocumentWorkspaceState({}));
      expect(result.current.hasLines).toBe(true);
    });
  });

  describe("the blank row a new form opens with", () => {
    const scanned = {
      _key: "scan-1",
      item_id: "item-1",
      name: "Lean Quark",
      quantity: 1,
      batch_number: "",
      expiry_date: "",
      notes: "",
    };

    it("goes when a scanned or chosen line arrives", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "OUT" }),
      );
      expect(result.current.lines).toHaveLength(1);

      act(() => result.current.addOrIncrementLine(scanned));

      expect(result.current.lines.map((l) => l.name)).toEqual(["Lean Quark"]);
    });

    it("goes when a quick-added line is appended", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "OUT" }),
      );

      act(() => result.current.appendLine(scanned));

      expect(result.current.lines.map((l) => l.name)).toEqual(["Lean Quark"]);
    });

    it("stays when the person asks for another blank row", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "OUT" }),
      );

      act(() => result.current.addEmptyLine());

      expect(result.current.lines).toHaveLength(2);
    });

    it.each([
      ["a quantity", { quantity: 7 }],
      ["a unit price", { unit_price: "12.34" }],
      ["a tax rate", { tax_rate: "23" }],
      ["a batch number", { batch_number: "B-1" }],
      ["an expiry date", { expiry_date: "2027-01-01" }],
      ["a note", { notes: "fragile" }],
    ])("does not take a row that only has %s typed in", (_label, patch) => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "OUT" }),
      );
      act(() => result.current.updateLine(0, patch));

      act(() => result.current.addOrIncrementLine(scanned));

      expect(result.current.lines).toHaveLength(2);
      expect(result.current.lines[0]).toMatchObject(patch);
    });

    it("does not take a row somebody already filled in", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "OUT" }),
      );
      act(() =>
        result.current.updateLine(0, { name: "Typed by hand", quantity: 3 }),
      );

      act(() => result.current.addOrIncrementLine(scanned));

      expect(result.current.lines.map((l) => l.name)).toEqual([
        "Typed by hand",
        "Lean Quark",
      ]);
    });
  });
  // A receipt puts products into stock, not words: a typed name has to be
  // picked from the list or made a product before the receipt is saved.
  describe("a receipt line names a product", () => {
    const typed = {
      _key: "typed",
      name: "Test laptop Dell",
      quantity: 1,
      batch_number: "",
      expiry_date: "",
      notes: "",
      unit_price: "3000",
      tax_rate: "",
    };

    it("refuses a line typed by hand, on the line", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "IN" }),
      );
      act(() => result.current.appendLine(typed));
      expect(result.current.validateForm()).toHaveProperty(
        "line.typed.name",
        "errors.lineNeedsProduct",
      );
    });

    it("takes the product the typed line was made into, at its price", () => {
      const { result } = renderHook(() =>
        useDocumentWorkspaceState({ initialType: "INTERNAL_IN" }),
      );
      act(() => result.current.appendLine(typed));
      act(() =>
        result.current.replaceLine("typed", {
          ...typed,
          _key: "made",
          name: "Dell laptop",
          product_template_id: "tpl-1",
          unit_price: "",
        }),
      );

      expect(result.current.lines).toHaveLength(1);
      expect(result.current.lines[0]).toMatchObject({
        _key: "typed",
        product_template_id: "tpl-1",
        unit_price: "3000",
      });
      expect(result.current.validateForm()).not.toHaveProperty(
        "line.typed.name",
      );
    });
  });
});
