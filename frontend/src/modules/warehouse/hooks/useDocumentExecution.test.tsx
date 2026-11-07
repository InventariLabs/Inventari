import { describe, expect, it, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { TFunction } from "i18next";
import i18n from "@/i18n/config";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import type { LabelScanView } from "@/types";
import {
  typedDoneQuantity,
  useDocumentExecution,
} from "./useDocumentExecution";
import { useDocumentScanResult } from "./useDocumentScanResult";

const t = ((key: string) => key) as unknown as TFunction;

/**
 * One document for the whole file, not one per render: the hook resets its
 * state whenever the document object changes, and a fresh literal would
 * erase the badge between the action and the assertion.
 */
const doc = {
  id: "doc-1",
  status: "CONFIRMED",
  lines: [
    {
      id: "line-1",
      document_id: "doc-1",
      name: "Sugar",
      barcode: "5901234123457",
      quantity: 12,
      expected_quantity: 12,
      done_quantity: 0,
      discrepancy_code: null,
      discrepancy_reason: null,
      uom: { id: "uom-kg", symbol: "kg", name: "Kilogram" },
    },
  ],
} as unknown as WarehouseDocument;

function renderExecution() {
  return renderHook(() =>
    useDocumentExecution({ document: doc, onSubmit: vi.fn(), t }),
  );
}

describe("useDocumentExecution — how much is done", () => {
  const withDone = (done: string) =>
    ({
      ...doc,
      lines: [{ ...doc.lines[0], done_quantity: done }],
    }) as unknown as WarehouseDocument;

  it("starts a line nobody has received on zero, not on the full quantity", () => {
    const untouched = withDone("0.000");
    const { result } = renderHook(() =>
      useDocumentExecution({ document: untouched, onSubmit: vi.fn(), t }),
    );

    expect(typedDoneQuantity(result.current.values, "line-1")).toBe("0");
  });

  it("starts a line on what the server reports as done, padding stripped", () => {
    const partial = withDone("4.000");
    const { result } = renderHook(() =>
      useDocumentExecution({ document: partial, onSubmit: vi.fn(), t }),
    );

    expect(typedDoneQuantity(result.current.values, "line-1")).toBe("4");
  });

  it("answers zero for a line with no entry yet, the one answer every reader shares", () => {
    expect(typedDoneQuantity({}, "line-1")).toBe("0");
  });
});

describe("useDocumentExecution — the recently-scanned mark", () => {
  it("does not mark a line whose quantity was typed", () => {
    // The badge said "Recently Scanned" over a line nobody scanned — the
    // number came from the keyboard, and the worker trusted a word that
    // claims a scan happened.
    const { result } = renderExecution();

    act(() => result.current.updateLineDoneQuantity("line-1", 5));

    expect(result.current.scannedLineId).toBeNull();
    // The focus cursor still moves: the panel advances to the next
    // incomplete line after any quantity action, typed ones included.
    expect(result.current.lastScannedLineId).toBe("line-1");
  });

  it("still marks the line a scan landed on", () => {
    const { result } = renderExecution();

    act(() => result.current.applyScanCode("5901234123457"));

    expect(result.current.scannedLineId).toBe("line-1");
  });

  it("takes the scan mark back when the same line is typed on", () => {
    const { result } = renderExecution();

    act(() => result.current.applyScanCode("5901234123457"));
    act(() => result.current.updateLineDoneQuantity("line-1", 3));

    expect(result.current.scannedLineId).toBeNull();
  });
});

describe("useDocumentExecution — a scan the registry recognized", () => {
  const labelScan = (item: Record<string, unknown>) =>
    ({
      status: "assigned",
      label_code: "STM-EHBH",
      action: "show_quick_actions",
      item,
    }) as unknown as LabelScanView;

  const lineOf = (extra: Record<string, unknown>) =>
    ({
      ...doc.lines[0],
      barcode: "snapshot-code",
      item_id: "item-1",
      product_template_id: "tpl-1",
      ...extra,
    }) as unknown as WarehouseDocument["lines"][number];

  function renderWith(line: WarehouseDocument["lines"][number]) {
    const document = { ...doc, lines: [line] } as WarehouseDocument;
    return renderHook(() => {
      const exec = useDocumentExecution({ document, onSubmit: vi.fn(), t });
      const applyScanResult = useDocumentScanResult(
        document.lines,
        exec.applyScanToLine,
        t,
      );
      return { ...exec, applyScanResult };
    });
  }

  it("counts the product on the document when scanned by its label", () => {
    const { result } = renderWith(lineOf({}));

    let handled = false;
    act(() => {
      handled = result.current.applyScanResult(
        labelScan({ id: "item-1", template_id: "tpl-1", name: "Quark" }),
      );
    });

    expect(handled).toBe(true);
    expect(result.current.scannedLineId).toBe("line-1");
  });

  it("counts it by its current barcode when the line recorded another", () => {
    // What /labels/scan answers for a catalogue product scanned by its EAN:
    // no item, the template inside stock_summary. The line was added with a
    // code the product has since replaced, and points at no stock record.
    const { result } = renderWith(
      lineOf({ item_id: null, barcode: "old-code" }),
    );

    act(() => {
      result.current.applyScanResult({
        status: "unassigned",
        label_code: "5901234123457",
        action: "show_quick_add",
        stock_summary: {
          template: { id: "tpl-1", name: "Quark" },
          total_quantity: 0,
          items: [],
        },
      } as unknown as LabelScanView);
    });

    expect(result.current.scannedLineId).toBe("line-1");
  });

  it("says a product that is not on the document is not on it", () => {
    const { result } = renderWith(lineOf({}));

    act(() => {
      result.current.applyScanResult(
        labelScan({ id: "item-9", template_id: "tpl-9", name: "Tofu" }),
      );
    });

    expect(result.current.scannedLineId).toBeNull();
    expect(result.current.scanFeedback).toBe(
      "warehouse:detail.scanNotOnDocument",
    );
    expect(result.current.scanFeedbackTone).toBe("error");
  });

  it("leaves other kinds of code to the shared resolver", () => {
    const { result } = renderWith(lineOf({}));

    let handled = true;
    act(() => {
      handled = result.current.applyScanResult({
        status: "storage_context",
        label_code: "X",
        action: "set_storage_context",
      } as LabelScanView);
    });

    expect(handled).toBe(false);
  });
});

describe("useDocumentExecution — goods held back from a receipt", () => {
  const receipt = {
    ...doc,
    type: "IN",
    lines: [
      {
        ...doc.lines[0],
        quantity: 10,
        expected_quantity: 10,
        done_quantity: 0,
      },
    ],
  } as unknown as WarehouseDocument;

  function renderReceipt() {
    const onSubmit = vi.fn();
    const utils = renderHook(() =>
      useDocumentExecution({ document: receipt, onSubmit, t }),
    );
    return { ...utils, onSubmit };
  }

  it("sends how much of the count is held back, under a held code", () => {
    const { result, onSubmit } = renderReceipt();

    act(() => result.current.updateLineDoneQuantity("line-1", 7));
    act(() => result.current.setHeldForLine("line-1", 3));
    act(() => result.current.handleSubmit());

    expect(onSubmit).toHaveBeenCalledWith({
      lines: [
        {
          line_id: "line-1",
          done_quantity: 7,
          held_quantity: 3,
          discrepancy_code: "DAMAGE",
        },
      ],
    });
  });

  it("will not hold more than arrived", () => {
    const { result, onSubmit } = renderReceipt();

    act(() => result.current.updateLineDoneQuantity("line-1", 7));
    act(() => result.current.setHeldForLine("line-1", 9));
    act(() => result.current.handleSubmit());

    // The setter clamps, and the payload carries the clamped figure.
    expect(result.current.heldValues["line-1"]).toBe("7");
    expect(onSubmit).toHaveBeenCalledWith({
      lines: [
        {
          line_id: "line-1",
          done_quantity: 7,
          held_quantity: 7,
          discrepancy_code: "DAMAGE",
        },
      ],
    });
  });

  it("keeps a held line an exception even when the delivery is full", () => {
    const { result } = renderReceipt();

    act(() => result.current.updateLineDoneQuantity("line-1", 10));
    act(() => result.current.setHeldForLine("line-1", 3));

    // Reaching the expected quantity clears a gap reason — but not the
    // reason goods are held back.
    expect(result.current.codes["line-1"]).toBe("DAMAGE");
  });
});

describe("useDocumentExecution — the scan sentence", () => {
  it("names the unit the way the reader's language writes it", () => {
    const pieces = {
      ...doc,
      lines: [
        { ...doc.lines[0], uom: { id: "u", symbol: "pcs", name: "Piece" } },
      ],
    } as unknown as WarehouseDocument;
    const { result } = renderHook(() =>
      useDocumentExecution({
        document: pieces,
        onSubmit: vi.fn(),
        t: i18n.getFixedT("pl") as unknown as TFunction,
      }),
    );

    act(() => result.current.applyScanCode("5901234123457"));

    expect(result.current.scanFeedback).toBe(
      "Zastosowano do Sugar: 1 / 12 szt.",
    );
  });
});
