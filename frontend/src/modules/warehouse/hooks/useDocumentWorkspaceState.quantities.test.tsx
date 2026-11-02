import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useDocumentWorkspaceState } from "./useDocumentWorkspaceState";
import type { WarehouseDocument } from "../types";

/**
 * A quantity that arrived over the wire is a number here, not text.
 *
 * The backend serialises Decimal as a JSON string, and the generated schema
 * says so — `DocumentLineSchema.quantity: string`. The hand-written type in
 * this module says `number`, so `tsc` had nothing to object to when the
 * consolidation added two of them: for lines typed into the form that was
 * addition, and for lines loaded from an existing document it was string
 * concatenation. Two units and three became twenty-three.
 */
const wireDocument = (quantity: unknown): WarehouseDocument =>
  ({
    id: "doc-1",
    type: "IN",
    status: "DRAFT",
    lines: [
      {
        id: "line-1",
        document_id: "doc-1",
        item_id: null,
        product_template_id: "tpl-1",
        name: "Kawa",
        brand: null,
        barcode: null,
        quantity,
        uom_id: null,
        batch_number: null,
        serial_number: null,
        expiry_date: null,
        notes: null,
        unit_price: null,
        tax_rate: null,
      },
    ],
  }) as unknown as WarehouseDocument;

describe("useDocumentWorkspaceState — quantities add up", () => {
  it("adds to a line that came from an existing document", () => {
    const { result } = renderHook(() =>
      useDocumentWorkspaceState({
        initialType: "IN",
        document: wireDocument("2.000"),
        partnersEnabled: false,
      }),
    );

    act(() => {
      result.current.addOrIncrementLine({
        _key: "k2",
        product_template_id: "tpl-1",
        name: "Kawa",
        quantity: 3,
        batch_number: "",
        expiry_date: "",
        notes: "",
        // The consolidation matches on the whole shape of a line, so the
        // fixture carries what the loaded line carries.
        uom_id: null,
        unit_price: "",
        tax_rate: "",
      } as never);
    });

    expect(result.current.lines).toHaveLength(1);
    expect(result.current.lines[0].quantity).toBe(5);
  });

  it("keeps the loaded quantity numeric before anything is added", () => {
    const { result } = renderHook(() =>
      useDocumentWorkspaceState({
        initialType: "IN",
        document: wireDocument("2.500"),
        partnersEnabled: false,
      }),
    );

    expect(result.current.lines[0].quantity).toBe(2.5);
  });

  it("consolidation adds two lines whose quantity arrived as text", () => {
    // appendLine is not the door: a caller consolidating right after
    // appending a line taken straight off a response hands consolidation
    // whatever that response carried — here the wire's decimal text. With
    // the raw addition this was "12.000" + 1 = "12.0001".
    const { result } = renderHook(() =>
      useDocumentWorkspaceState({ initialType: "IN", partnersEnabled: false }),
    );

    const wireShapedLine = (quantity: unknown, key: string) =>
      ({
        _key: key,
        item_id: "item-1",
        name: "Kawa",
        quantity,
        uom_id: null,
        batch_number: "",
        expiry_date: "",
        notes: "",
        unit_price: "",
        tax_rate: "",
      }) as never;

    act(() => result.current.updateLine(0, wireShapedLine("12.000", "k1")));
    act(() => result.current.appendLine(wireShapedLine(1, "k2")));
    act(() => result.current.consolidateLines());

    expect(result.current.lines).toHaveLength(1);
    expect(result.current.lines[0].quantity).toBe(13);
  });
});
