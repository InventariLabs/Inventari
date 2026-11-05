import { describe, expect, it, vi, type Mock } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { toast } from "sonner";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { useDocumentActions } from "./useDocumentActions";

// Where Execute leads asks the picking session; these tests are about the
// actions, so no session is open.
vi.mock("@/modules/warehouse/hooks/useDocumentScanSession", () => ({
  useDocumentScanSession: () => ({ data: null, isPending: false }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const routerWrapper = ({ children }: { children: ReactNode }) => (
  <BrowserRouter>{children}</BrowserRouter>
);

function makeMutations() {
  return {
    confirmMutate: vi.fn(),
    postNowMutate: vi.fn(),
    completeMutate: vi.fn(),
    cancelMutate: vi.fn(),
    deleteMutate: vi.fn(),
    undoMutate: vi.fn(),
  };
}

const mutationShape = (mutate: Mock) => ({
  mutate,
  isPending: false,
});

function renderActions(
  docStatus?: string,
  doc?: Parameters<typeof useDocumentActions>[0]["doc"],
) {
  const m = makeMutations();
  const utils = renderHook(
    () =>
      useDocumentActions({
        docId: "doc-1",
        doc,
        docStatus,
        duplicateMutation: { mutateAsync: vi.fn() },
        confirmMutation: mutationShape(m.confirmMutate),
        postNowMutation: mutationShape(m.postNowMutate),
        completeMutation: mutationShape(m.completeMutate),
        cancelMutation: mutationShape(m.cancelMutate),
        deleteMutation: mutationShape(m.deleteMutate),
        undoMutation: mutationShape(m.undoMutate),
      }),
    { wrapper: routerWrapper },
  );
  return { m, utils };
}

describe("useDocumentActions.handleApplyCorrection", () => {
  it("confirms then completes for a DRAFT correction", () => {
    const { m, utils } = renderActions("DRAFT");

    act(() => utils.result.current.handleApplyCorrection());

    expect(m.confirmMutate).toHaveBeenCalledOnce();
    // The confirm onSuccess callback must then trigger the complete call.
    const onSuccess = m.confirmMutate.mock.calls[0][1].onSuccess;
    act(() => onSuccess());
    expect(m.completeMutate).toHaveBeenCalledWith(
      { id: "doc-1" },
      expect.any(Object),
    );
  });

  it("skips confirm and re-completes for a CONFIRMED correction", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleApplyCorrection());

    expect(m.confirmMutate).not.toHaveBeenCalled();
    expect(m.completeMutate).toHaveBeenCalledWith(
      { id: "doc-1" },
      expect.any(Object),
    );
  });

  it("shows a translated product-aware toast for CORRECTION_ITEM_MISSING", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleApplyCorrection());

    const onError = m.completeMutate.mock.calls[0][1].onError;
    const structuredError = {
      isAxiosError: true,
      response: {
        data: {
          detail: {
            code: "CORRECTION_ITEM_MISSING",
            message: "Widget no longer exists in the catalog…",
            product: "Widget",
          },
        },
      },
    };
    act(() => onError(structuredError));

    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Widget"));
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("no longer exists in the catalog"),
    );
  });

  it("opens the unit dialog instead of toasting when the correction stops on a unit mismatch", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleApplyCorrection());
    const onError = m.completeMutate.mock.calls[0][1].onError;
    act(() =>
      onError({
        isAxiosError: true,
        response: {
          data: {
            detail: {
              code: "RECORD_UNIT_MISMATCH",
              message:
                "Widget is kept in g, and this record would be saved in kg.",
              product: "Widget",
              template_unit: "g",
              chosen_unit: "kg",
            },
          },
        },
      }),
    );

    expect(toast.error).not.toHaveBeenCalled();
    expect(utils.result.current.unitMismatch).toEqual({
      product: "Widget",
      templateUnit: "g",
      chosenUnit: "kg",
      payload: {},
    });
    act(() => utils.result.current.confirmUnitChoice());
    expect(m.completeMutate).toHaveBeenLastCalledWith(
      { id: "doc-1", data: { unit_confirmed_over_template: true } },
      expect.any(Object),
    );
  });

  it("falls back to the generic complete error for unknown codes", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleApplyCorrection());

    const onError = m.completeMutate.mock.calls[0][1].onError;
    const plainError = {
      isAxiosError: true,
      response: { data: { detail: "Something else broke" } },
    };
    act(() => onError(plainError));

    expect(toast.error).toHaveBeenCalledWith("Something else broke");
  });
});

describe("useDocumentActions session completion", () => {
  it("completes payload-free and reports the backorder the session created", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleSessionComplete());

    // No execution payload: the scanning session already wrote the received
    // quantities onto the document's lines, and a payload naming some lines
    // would book every other line as delivered in full.
    expect(m.completeMutate.mock.calls[0][0]).toEqual({ id: "doc-1" });
    const onSuccess = m.completeMutate.mock.calls[0][1].onSuccess;
    act(() =>
      onSuccess({
        id: "doc-1",
        status: "COMPLETED",
        generated_backorder_id: "bo-1",
        generated_backorder_number: "IN/2026/014",
      }),
    );

    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("IN/2026/014"),
      expect.objectContaining({
        action: expect.objectContaining({ label: expect.any(String) }),
      }),
    );
  });

  it("says the document completed when there is no backorder", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleSessionComplete());
    const onSuccess = m.completeMutate.mock.calls[0][1].onSuccess;
    act(() => onSuccess({ id: "doc-1", status: "COMPLETED" }));

    expect(toast.success).toHaveBeenCalledWith(expect.any(String));
    expect(utils.result.current.executionOpen).toBe(false);
  });

  it("carries a dispatch's shipment and still names no line", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() =>
      utils.result.current.handleSessionComplete({
        carrier: "DPD",
        tracking_number: "X2",
      }),
    );

    expect(m.completeMutate.mock.calls[0][0]).toEqual({
      id: "doc-1",
      data: { shipment: { carrier: "DPD", tracking_number: "X2" } },
    });
  });
});

describe("useDocumentActions unit mismatch", () => {
  const payload = { lines: [{ line_id: "l1", done_quantity: 2 }] };
  const mismatchError = {
    isAxiosError: true,
    response: {
      data: {
        detail: {
          code: "RECORD_UNIT_MISMATCH",
          message: "Widget is kept in g, and this record would be saved in kg.",
          product: "Widget",
          template_unit: "g",
          chosen_unit: "kg",
        },
      },
    },
  };

  it("opens the dialog instead of toasting when a completion stops on the mismatch", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleComplete(payload));
    const onError = m.completeMutate.mock.calls[0][1].onError;
    act(() => onError(mismatchError));

    expect(toast.error).not.toHaveBeenCalled();
    expect(utils.result.current.unitMismatch).toEqual({
      product: "Widget",
      templateUnit: "g",
      chosenUnit: "kg",
      payload,
    });
  });

  it("retries the completion with the confirmation on the same payload", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleComplete(payload));
    act(() => m.completeMutate.mock.calls[0][1].onError(mismatchError));
    act(() => utils.result.current.confirmUnitChoice());

    expect(m.completeMutate).toHaveBeenLastCalledWith(
      {
        id: "doc-1",
        data: { ...payload, unit_confirmed_over_template: true },
      },
      expect.any(Object),
    );
    // the dialog is down the moment the retry fires
    expect(utils.result.current.unitMismatch).toBeNull();
  });

  it("dismisses without retrying", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleComplete(payload));
    act(() => m.completeMutate.mock.calls[0][1].onError(mismatchError));
    act(() => utils.result.current.dismissUnitMismatch());

    expect(utils.result.current.unitMismatch).toBeNull();
    expect(m.completeMutate).toHaveBeenCalledOnce();
  });

  it("toasts the completed state once the confirmed retry lands", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleComplete(payload));
    act(() => m.completeMutate.mock.calls[0][1].onError(mismatchError));
    act(() => utils.result.current.confirmUnitChoice());
    const onRetrySuccess = m.completeMutate.mock.calls[1][1].onSuccess;
    act(() => onRetrySuccess({ id: "doc-1", status: "COMPLETED" }));

    expect(toast.success).toHaveBeenCalledWith(expect.any(String));
    expect(utils.result.current.executionOpen).toBe(false);
  });
});

describe("useDocumentActions receipt expiry", () => {
  const payload = {
    lines: [
      { line_id: "l1", done_quantity: 2 },
      { line_id: "l2", done_quantity: 3 },
    ],
  };
  const refusal = {
    isAxiosError: true,
    response: {
      data: {
        detail: {
          code: "RECEIPT_EXPIRY_REQUIRED",
          message:
            "A product taken by earliest expiry cannot be received without an expiry date",
          lines: [
            { line_id: "l1", line_number: 1, product: "Yoghurt" },
            { line_id: "l2", line_number: 2, product: "Butter" },
          ],
        },
      },
    },
  };

  it("asks for the first undated line instead of toasting the refusal", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleComplete(payload));
    act(() => m.completeMutate.mock.calls[0][1].onError(refusal));

    expect(toast.error).not.toHaveBeenCalled();
    expect(utils.result.current.receiptExpiry?.prompt).toEqual({
      lineId: "l1",
      product: "Yoghurt",
    });
  });

  it("keeps the dialog up for the next undated line without retrying yet", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleComplete(payload));
    act(() => m.completeMutate.mock.calls[0][1].onError(refusal));
    act(() =>
      utils.result.current.receiptExpiry?.onConfirm("LOT-1", "2027-01-31"),
    );

    expect(utils.result.current.receiptExpiry?.prompt).toEqual({
      lineId: "l2",
      product: "Butter",
    });
    expect(m.completeMutate).toHaveBeenCalledOnce();
  });

  it("retries the same payload with the lot and expiry of every line", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleComplete(payload));
    act(() => m.completeMutate.mock.calls[0][1].onError(refusal));
    act(() =>
      utils.result.current.receiptExpiry?.onConfirm("LOT-1", "2027-01-31"),
    );
    act(() => utils.result.current.receiptExpiry?.onConfirm("", "2027-02-28"));

    expect(m.completeMutate).toHaveBeenLastCalledWith(
      {
        id: "doc-1",
        data: {
          lines: [
            {
              line_id: "l1",
              done_quantity: 2,
              expiry_date: "2027-01-31",
              batch_number: "LOT-1",
            },
            { line_id: "l2", done_quantity: 3, expiry_date: "2027-02-28" },
          ],
        },
      },
      expect.any(Object),
    );
    expect(utils.result.current.receiptExpiry).toBeNull();
  });

  it("dismisses without retrying the completion", () => {
    const { m, utils } = renderActions("CONFIRMED");

    act(() => utils.result.current.handleComplete(payload));
    act(() => m.completeMutate.mock.calls[0][1].onError(refusal));
    act(() => utils.result.current.receiptExpiry?.onClose());

    expect(utils.result.current.receiptExpiry).toBeNull();
    expect(m.completeMutate).toHaveBeenCalledOnce();
  });

  it("asks for the dates a one-step posting needs and posts the draft again with them", () => {
    const oneLine = {
      isAxiosError: true,
      response: {
        data: {
          detail: {
            code: "RECEIPT_EXPIRY_REQUIRED",
            message: "A product taken by earliest expiry needs a date",
            lines: [{ line_id: "l1", line_number: 1, product: "Yoghurt" }],
          },
        },
      },
    };
    const { m, utils } = renderActions("DRAFT");

    act(() => utils.result.current.setConfirmAction("postNow"));
    act(() => utils.result.current.handleAction());
    expect(m.postNowMutate).toHaveBeenCalledWith(
      { id: "doc-1" },
      expect.any(Object),
    );

    act(() => m.postNowMutate.mock.calls[0][1].onError(oneLine));
    expect(toast.error).not.toHaveBeenCalled();
    expect(utils.result.current.receiptExpiry?.prompt).toEqual({
      lineId: "l1",
      product: "Yoghurt",
    });

    act(() =>
      utils.result.current.receiptExpiry?.onConfirm("LOT-9", "2027-04-01"),
    );

    expect(m.postNowMutate).toHaveBeenLastCalledWith(
      {
        id: "doc-1",
        data: {
          lines: [
            {
              line_id: "l1",
              batch_number: "LOT-9",
              expiry_date: "2027-04-01",
            },
          ],
        },
      },
      expect.any(Object),
    );
  });

  it("builds the session's close from the document's own quantities", () => {
    const doc = {
      id: "doc-1",
      lines: [
        {
          id: "l1",
          done_quantity: "2",
          held_quantity: "0",
          discrepancy_code: null,
          discrepancy_reason: null,
        },
        {
          id: "l2",
          done_quantity: "1",
          held_quantity: "0",
          discrepancy_code: "SHORTAGE",
          discrepancy_reason: "one did not arrive",
        },
      ],
    } as unknown as WarehouseDocument;
    const { m, utils } = renderActions("CONFIRMED", doc);

    act(() => utils.result.current.handleSessionComplete());
    act(() => m.completeMutate.mock.calls[0][1].onError(refusal));
    act(() =>
      utils.result.current.receiptExpiry?.onConfirm("LOT-1", "2027-01-31"),
    );
    act(() => utils.result.current.receiptExpiry?.onConfirm("", "2027-02-28"));

    expect(m.completeMutate).toHaveBeenLastCalledWith(
      {
        id: "doc-1",
        data: {
          lines: [
            {
              line_id: "l1",
              done_quantity: 2,
              expiry_date: "2027-01-31",
              batch_number: "LOT-1",
            },
            {
              line_id: "l2",
              done_quantity: 1,
              expiry_date: "2027-02-28",
              discrepancy_code: "SHORTAGE",
              discrepancy_reason: "one did not arrive",
            },
          ],
        },
      },
      expect.any(Object),
    );
  });
});

describe("useDocumentActions one-step posting", () => {
  it("posts the draft through the post-now mutation", () => {
    const { m, utils } = renderActions("DRAFT");

    act(() => utils.result.current.setConfirmAction("postNow"));
    act(() => utils.result.current.handleAction());

    expect(m.postNowMutate).toHaveBeenCalledWith(
      { id: "doc-1" },
      expect.any(Object),
    );
    expect(m.confirmMutate).not.toHaveBeenCalled();
  });

  it("says the stock moved once the posting lands", () => {
    const { m, utils } = renderActions("DRAFT");

    act(() => utils.result.current.setConfirmAction("postNow"));
    act(() => utils.result.current.handleAction());
    const onSuccess = m.postNowMutate.mock.calls[0][1].onSuccess;
    act(() => onSuccess({ id: "doc-1", status: "COMPLETED" }));

    expect(toast.success).toHaveBeenCalled();
    expect(utils.result.current.confirmAction).toBeNull();
  });

  it("says the document went for approval when the profile requires one", () => {
    const { m, utils } = renderActions("DRAFT");

    act(() => utils.result.current.setConfirmAction("postNow"));
    act(() => utils.result.current.handleAction());
    const onSuccess = m.postNowMutate.mock.calls[0][1].onSuccess;
    act(() => onSuccess({ id: "doc-1", status: "PENDING_APPROVAL" }));

    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("approval"),
    );
    expect(utils.result.current.confirmAction).toBeNull();
  });
});
