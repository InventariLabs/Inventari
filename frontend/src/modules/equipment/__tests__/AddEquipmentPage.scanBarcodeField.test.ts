import { describe, expect, it } from "vitest";
import { barcodeScanTarget } from "../pages/AddEquipmentPage";
import type { LabelScanView } from "@/types";

/**
 * The scan button beside Barcode / EAN decrypts whatever the printed code
 * carries. A label's QR carries a whole address, and the field it was
 * scanned into records a manufacturer code — these are the decisions
 * between the two.
 */

const assignedLabel = {
  status: "assigned",
  label_code: "STM-EHBH",
  message_key: "scan:result.product",
  message_params: { product: "Spaghetti 500g" },
  action: "show_quick_actions",
  item: { id: "i1", name: "Spaghetti 500g" },
} as unknown as LabelScanView;

const blankLabel = {
  status: "unassigned",
  label_code: "STM-Y3GI",
  message_key: "scan:result.labelReady",
  action: "show_quick_add",
  context_tag: "equipment",
} as LabelScanView;

const barcodeInStock = {
  status: "product_stock",
  label_code: "5907770001112",
  message_key: "scan:result.product",
  message_params: { product: "Spaghetti 500g" },
  action: "show_stock_actions",
  stock_summary: {
    total_quantity: 3,
    unit: "pcs",
    template: { id: "t1", name: "Spaghetti 500g" },
    items: [],
  },
} as unknown as LabelScanView;

const unknownBarcode = {
  status: "unassigned",
  label_code: "999999999999",
  message_key: "scan:result.newProduct",
  action: "show_quick_add",
} as LabelScanView;

const barcodeFromHistory = {
  status: "unassigned",
  label_code: "5905550002229",
  message_key: "scan:result.foundInHistory",
  message_params: { product: "Old Coffee" },
  action: "show_quick_add",
  stock_summary: {
    total_quantity: 0,
    items: [],
    template: { id: "t2", name: "Old Coffee" },
  },
} as unknown as LabelScanView;

const archivedLabel = {
  status: "archived",
  label_code: "STM-OLD1",
  message_key: "scan:result.previously",
  message_params: { product: "Retired Printer" },
  action: "show_archived_info",
  item: { id: "i2", name: "Retired Printer" },
} as unknown as LabelScanView;

describe("barcodeScanTarget", () => {
  it("keeps a taken label's address out of the field and leaves it to be named", () => {
    // Scanning the QR of a label stuck to another product used to write
    // 'http://localhost:5773/s/STM-EHBH' into Barcode / EAN. Nothing is
    // written now; the resolver names the product and offers a way through.
    expect(barcodeScanTarget(assignedLabel)).toEqual({ place: "elsewhere" });
  });

  it("sends a blank label to the label field, as the code it carries", () => {
    expect(barcodeScanTarget(blankLabel)).toEqual({
      place: "label",
      code: "STM-Y3GI",
    });
  });

  it("records a barcode in the field and names the product it belongs to", () => {
    expect(barcodeScanTarget(barcodeInStock)).toEqual({
      place: "barcode",
      code: "5907770001112",
      product: "Spaghetti 500g",
    });
  });

  it("records a barcode no product holds, without calling it a label", () => {
    // The registry answers an unknown EAN with the same 'show_quick_add'
    // action a blank label gets; the hyphen in a label code is what tells
    // the two apart (backend/app/core/label_codes.py).
    expect(barcodeScanTarget(unknownBarcode)).toEqual({
      place: "barcode",
      code: "999999999999",
      product: null,
    });
  });

  it("names a product known only from history", () => {
    expect(barcodeScanTarget(barcodeFromHistory)).toEqual({
      place: "barcode",
      code: "5905550002229",
      product: "Old Coffee",
    });
  });

  it("leaves an archived record's label to the resolver", () => {
    expect(barcodeScanTarget(archivedLabel)).toEqual({ place: "elsewhere" });
  });

  it("leaves a location or a document to the resolver", () => {
    const storage = {
      status: "storage_context",
      label_code: "LOC-7",
      action: "set_storage_context",
      location: { id: "s1", name: "Server Room", icon: "📦" },
    } as unknown as LabelScanView;
    expect(barcodeScanTarget(storage)).toEqual({ place: "elsewhere" });

    const document = {
      status: "document",
      label_code: "IN/2026/001",
      action: "open_document",
      document: { id: "d1", number: "IN/2026/001", type: "IN" },
    } as unknown as LabelScanView;
    expect(barcodeScanTarget(document)).toEqual({ place: "elsewhere" });
  });
});
