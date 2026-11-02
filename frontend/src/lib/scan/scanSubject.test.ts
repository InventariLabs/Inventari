import { describe, it, expect } from "vitest";
import {
  documentScanTarget,
  scanSubject,
  scanSubjectKind,
} from "@/lib/scan/scanSubject";
import type { LabelScanView } from "@/types";

const base = {
  label_code: "STM-0001",
  message: "",
} as unknown as LabelScanView;

const doc = (
  mode: LabelScanView["document_mode"],
  type: string,
): LabelScanView => ({
  ...base,
  status: "document",
  action: "open_document",
  document: { id: "d1", number: "IN/2026/049", status: "DRAFT", type },
  document_mode: mode,
});

describe("scanSubjectKind", () => {
  it("names a document", () => {
    expect(scanSubjectKind(doc("preview", "IN"))).toBe("document");
  });

  it("names a storage location", () => {
    expect(
      scanSubjectKind({
        ...base,
        status: "storage_context",
        action: "set_storage_context",
        location: { id: "s1", name: "Cold Storage A", icon: "📦" },
      }),
    ).toBe("storage");
  });

  it("separates a blank label from a known product", () => {
    expect(
      scanSubjectKind({
        ...base,
        status: "unassigned",
        action: "show_quick_add",
      }),
    ).toBe("blankLabel");
    expect(
      scanSubjectKind({
        ...base,
        status: "unassigned",
        action: "show_quick_add",
        stock_summary: {
          total_quantity: 0,
          unit: "pcs",
          items: [],
          template: { name: "Flour" },
        },
      }),
    ).toBe("product");
  });
});

describe("documentScanTarget", () => {
  it("continues a draft in the edit form", () => {
    expect(documentScanTarget(doc("continue", "IN"))).toBe(
      "/warehouse/documents/d1#edit",
    );
  });

  it("sends a confirmed receipt to receiving and an issue to picking", () => {
    expect(documentScanTarget(doc("execute", "IN"))).toBe(
      "/warehouse/documents/d1#receive",
    );
    expect(documentScanTarget(doc("execute", "OUT"))).toBe(
      "/warehouse/documents/d1#pick",
    );
    expect(documentScanTarget(doc("execute", "MM"))).toBe(
      "/warehouse/documents/d1#execute",
    );
  });

  it("opens anything finished as a preview", () => {
    expect(documentScanTarget(doc("preview", "IN"))).toBe(
      "/warehouse/documents/d1",
    );
  });

  it("has nothing to say about a code that is not a document", () => {
    expect(
      documentScanTarget({
        ...base,
        status: "product_stock",
        action: "show_stock_actions",
      }),
    ).toBeNull();
  });
});

describe("scanSubject", () => {
  it("names a document by its number", () => {
    expect(scanSubject(doc("preview", "IN"), "IN/2026/049")).toEqual({
      kind: "document",
      name: "IN/2026/049",
      target: "/warehouse/documents/d1",
    });
  });

  it("keeps the scanned code when it offers to hand the reader on", () => {
    const subject = scanSubject(
      {
        ...base,
        status: "product_stock",
        action: "show_stock_actions",
        stock_summary: {
          total_quantity: 3,
          unit: "pcs",
          items: [],
          template: { name: "Flour" },
        },
      },
      "5901234123457",
    );
    expect(subject.name).toBe("Flour");
    expect(subject.target).toBe("/scan?code=5901234123457");
  });

  it("escapes a code that would otherwise break the query string", () => {
    const subject = scanSubject(
      { ...base, status: "unassigned", action: "show_quick_add" },
      "IN/2026/049",
    );
    expect(subject.target).toBe("/scan?code=IN%2F2026%2F049");
  });
});
