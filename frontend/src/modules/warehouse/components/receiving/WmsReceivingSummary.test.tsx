import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import WmsReceivingSummary from "./WmsReceivingSummary";
import type { WmsReceiveLine } from "@/modules/warehouse/api/documents_receiving";
import { render } from "@/test/utils";

/**
 * The summary is the screen a stockkeeper reads to decide whether to file
 * a claim. It used to list only received and short lines while counting
 * every line into its denominator, so a skipped line's ten units went
 * missing from exactly the list that had to account for them.
 */

const lines: WmsReceiveLine[] = [
  {
    id: "line-1",
    document_line_id: "dl-1",
    from_order: false,
    expected_is_count: false,
    pick_order: 1,
    status: "received",
    received_quantity: 8,
    product_name: "Olive oil 1L",
    lot_name: null,
    expected_quantity: 10,
    uom_symbol: "pcs",
  },
  {
    id: "line-2",
    document_line_id: "dl-2",
    from_order: false,
    expected_is_count: false,
    pick_order: 2,
    status: "skipped",
    received_quantity: 0,
    product_name: "Flour 1kg",
    lot_name: null,
    expected_quantity: 10,
    uom_symbol: "pcs",
  },
  {
    id: "line-3",
    document_line_id: "dl-3",
    from_order: false,
    expected_is_count: false,
    pick_order: 3,
    status: "received",
    received_quantity: 10,
    product_name: "Sugar 1kg",
    lot_name: null,
    expected_quantity: 10,
    uom_symbol: "pcs",
  },
];

function renderSummary(rows: WmsReceiveLine[] = lines) {
  return render(
    <WmsReceivingSummary lines={rows} onClose={vi.fn()} onShown={vi.fn()} />,
  );
}

describe("WmsReceivingSummary — the list accounts for every expected unit", () => {
  it("keeps the skipped line on the list the claim is filed from", () => {
    renderSummary();

    expect(screen.getByText("Olive oil 1L")).toBeInTheDocument();
    expect(screen.getByText("Flour 1kg")).toBeInTheDocument();
    expect(screen.getByText("Sugar 1kg")).toBeInTheDocument();
  });

  it("marks the skipped line instead of letting it pass as received", () => {
    renderSummary();

    expect(screen.getByText("Skipped")).toBeInTheDocument();
    expect(screen.getByText("0/10 pcs.")).toBeInTheDocument();
  });

  it("counts the same set the list shows", () => {
    renderSummary();

    expect(screen.getByText("18 of 30 pcs. received")).toBeInTheDocument();
  });

  it("counts each unit on its own when the lines disagree on the unit", () => {
    const mixed: WmsReceiveLine[] = [
      { ...lines[0], uom_symbol: "pcs" },
      { ...lines[1], uom_symbol: "kg", expected_quantity: 2.5 },
      { ...lines[2], uom_symbol: "pcs" },
    ];
    renderSummary(mixed);

    // 18 pieces and 0 kilograms, never "18 of 22.5 units".
    expect(screen.getByText("18 of 20 pcs. received")).toBeInTheDocument();
    expect(screen.getByText("0 of 2.5 kg received")).toBeInTheDocument();
    expect(screen.queryByText(/22\.5/)).not.toBeInTheDocument();
  });

  it("says how much of a received line is held back before the stock is booked", () => {
    renderSummary([{ ...lines[2], held_quantity: 10 }]);

    // The count alone reads as ten good pieces. The summary is the last
    // screen before completion, so it has to say that none of them is usable.
    expect(screen.getByText("Quarantined: 10 pcs.")).toBeInTheDocument();
  });

  it("keeps lines with no unit out of a named unit's count", () => {
    const partlyUnitless: WmsReceiveLine[] = [
      lines[0],
      { ...lines[2], uom_symbol: null },
    ];
    renderSummary(partlyUnitless);

    expect(screen.getByText("8 of 10 pcs. received")).toBeInTheDocument();
    expect(screen.getByText("10 of 10 units received")).toBeInTheDocument();
  });
});

describe("WmsReceivingSummary — one exit, and it says what it does", () => {
  // Closing the summary completes the document and books the stock, so no
  // unlabelled control may reach that handler: the corner X, Escape and the
  // backdrop used to book stock without a word about it.
  it("has no close control but the one that says it posts stock", () => {
    const onClose = vi.fn();
    render(<WmsReceivingSummary lines={lines} onClose={onClose} />);

    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
    fireEvent.keyDown(document.activeElement ?? document.body, {
      key: "Escape",
    });
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /post stock/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("WmsReceivingSummary — a skipped line waits for an answer", () => {
  function renderAnswering() {
    const onClose = vi.fn();
    const onUndoSkip = vi.fn();
    const onAnswerSkip = vi.fn();
    render(
      <WmsReceivingSummary
        lines={lines}
        onClose={onClose}
        onUndoSkip={onUndoSkip}
        onAnswerSkip={onAnswerSkip}
      />,
    );
    return { onClose, onUndoSkip, onAnswerSkip };
  }

  it("will not complete the document while the skipped line has no answer", () => {
    const { onClose } = renderAnswering();

    fireEvent.click(screen.getByRole("button", { name: /post stock/i }));

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Answer every skipped line first",
    );
  });

  it("takes the skip back, or says the missing goods are owed or not coming", () => {
    const { onUndoSkip, onAnswerSkip } = renderAnswering();

    fireEvent.click(screen.getByRole("button", { name: "Undo skip" }));
    fireEvent.click(screen.getByRole("button", { name: "Backorder" }));
    fireEvent.click(screen.getByRole("button", { name: "Not coming" }));

    expect(onUndoSkip).toHaveBeenCalledWith(lines[1]);
    expect(onAnswerSkip).toHaveBeenNthCalledWith(1, lines[1], "SHORTAGE");
    expect(onAnswerSkip).toHaveBeenNthCalledWith(2, lines[1], "OTHER");
  });

  it("completes once no line is left skipped", () => {
    const onClose = vi.fn();
    render(
      <WmsReceivingSummary
        lines={lines.map((ln) =>
          ln.status === "skipped" ? { ...ln, status: "short" } : ln,
        )}
        onClose={onClose}
        onUndoSkip={vi.fn()}
        onAnswerSkip={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Undo skip" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /post stock/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
