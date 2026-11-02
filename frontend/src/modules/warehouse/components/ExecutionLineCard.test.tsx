import { fireEvent, render, screen } from "@/test/utils";
import { describe, expect, it, vi } from "vitest";
import type { TFunction } from "i18next";
import { ExecutionLineCard } from "./ExecutionLineCard";
import { documentLine } from "@/test/factories/documents";
import i18n from "@/i18n/config";

const t = ((key: string) => key) as unknown as TFunction;

const line = documentLine({
  id: "line-1",
  document_id: "doc-1",
  item_id: "item-1",
  product_template_id: null,
  name: "Sugar",
  brand: null,
  barcode: null,
  quantity: "12",
  expected_quantity: "12",
  done_quantity: "0",
  batch_number: null,
  expiry_date: null,
  notes: null,
  line_number: 1,
  uom: { id: "uom-kg", symbol: "kg", name: "Kilogram", rounding: "0.001" },
});

function makeProps() {
  return {
    line,
    documentStatus: "CONFIRMED",
    currentDoneQuantity: 0,
    isReceipt: false,
    requiresDiscrepancy: false,
    isActiveScanLine: false,
    lastScannedLineId: null,
    isReasonEditorOpen: false,
    executionLineStatus: "PENDING" as const,
    values: {} as Record<string, string>,
    heldValues: {} as Record<string, string>,
    codes: {},
    reasons: {},
    onUpdateDoneQuantity: vi.fn(),
    onHeldChange: vi.fn(),
    onCodeChange: vi.fn(),
    onReasonToggle: vi.fn(),
    onReasonChange: vi.fn(),
    t,
  };
}

function doneField() {
  return screen.getByRole("spinbutton", { name: /doneQuantityLabel/i });
}

describe("ExecutionLineCard — done quantity field", () => {
  // While "12.5" is typed, the number field reports the dot step
  // as "". The card used to answer that with Number("") === 0 — the round
  // trip through the numeric store rewrote the field to "0" and ate the
  // dot, so receiving twelve and a half kilos landed as five.
  it("does not report zero for the dot step's empty report", () => {
    const props = makeProps();
    render(<ExecutionLineCard {...props} />);

    fireEvent.change(doneField(), { target: { value: "1" } });
    fireEvent.change(doneField(), { target: { value: "12" } });
    expect(props.onUpdateDoneQuantity).toHaveBeenCalledWith("line-1", 12);

    fireEvent.change(doneField(), { target: { value: "" } });
    expect(doneField()).toHaveValue(null);
    expect(props.onUpdateDoneQuantity).not.toHaveBeenCalledWith("line-1", 0);

    fireEvent.change(doneField(), { target: { value: "12.5" } });
    expect(props.onUpdateDoneQuantity).toHaveBeenCalledWith("line-1", 12.5);
  });
});

describe("ExecutionLineCard — held back goods", () => {
  it("asks how much of a receipt is held back", () => {
    render(<ExecutionLineCard {...makeProps()} isReceipt />);

    expect(
      screen.getByRole("spinbutton", { name: /heldQuantityLabel/i }),
    ).toBeInTheDocument();
  });

  it("shows the held codes, and no gap codes, once goods are held", () => {
    render(
      <ExecutionLineCard
        {...makeProps()}
        isReceipt
        currentDoneQuantity={12}
        heldValues={{ "line-1": "3" }}
        codes={{ "line-1": "DAMAGE" }}
      />,
    );

    const select = screen.getByLabelText(/discrepancyCodeLabel/i);
    expect(select).toHaveValue("DAMAGE");
    expect(
      screen.queryByRole("option", { name: /discrepancyCodes.SHORTAGE/i }),
    ).toBeNull();
    expect(
      screen.getByRole("option", { name: /discrepancyCodes.QUALITY_HOLD/i }),
    ).toBeInTheDocument();
  });

  it("does not offer to hold goods back on a dispatch", () => {
    render(<ExecutionLineCard {...makeProps()} isReceipt={false} />);

    expect(
      screen.queryByRole("spinbutton", { name: /heldQuantityLabel/i }),
    ).toBeNull();
  });
});

describe("ExecutionLineCard — the planned quantity reads like the rest of the card", () => {
  // The meta line handed the raw number to the translation ("12.5") while the
  // execution summary above it formats by the interface language ("12,5"), so
  // one screen printed the same quantity with two decimal separators.
  it("writes the planned and remaining quantity in the interface language", async () => {
    await i18n.changeLanguage("pl");
    try {
      const calls: Array<Record<string, unknown>> = [];
      const spyT = ((key: string, options?: Record<string, unknown>) => {
        if (key === "warehouse:detail.executionMeta" && options)
          calls.push(options);
        return key;
      }) as unknown as TFunction;
      const props = makeProps();
      const { unmount } = render(
        <ExecutionLineCard
          {...props}
          t={spyT}
          line={{ ...line, quantity: "12.5", expected_quantity: "12.5" }}
        />,
      );

      expect(calls[0]).toMatchObject({ expected: "12,5", remaining: "12,5" });
      unmount();
    } finally {
      await i18n.changeLanguage("en");
    }
  });
});
