import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { toast } from "sonner";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { useDocumentActions } from "../hooks/useDocumentActions";

// Where Execute leads asks the picking session; these tests are about the
// actions, so no session is open.
vi.mock("@/modules/warehouse/hooks/useDocumentScanSession", () => ({
  useDocumentScanSession: () => ({ data: null, isPending: false }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <MemoryRouter>{children}</MemoryRouter>
);

/** Minimal mutation stub that synchronously resolves onSuccess with `data`. */
function resolvingMutation(data: Partial<WarehouseDocument>) {
  return {
    mutate: vi.fn(
      (
        _id: string,
        opts?: {
          onSuccess?: (data?: WarehouseDocument) => void;
          onError?: (err: unknown) => void;
        },
      ) => {
        opts?.onSuccess?.(data as unknown as WarehouseDocument);
      },
    ),
    isPending: false,
  };
}

function rejectingCompleteMutation(detail: { code: string; message: string }) {
  const axiosLike = {
    isAxiosError: true,
    response: { data: { detail } },
  };
  return {
    mutate: vi.fn(
      (
        _payload: { id: string; data?: unknown },
        opts?: {
          onSuccess?: (data?: WarehouseDocument) => void;
          onError?: (err: unknown) => void;
        },
      ) => {
        opts?.onError?.(axiosLike);
      },
    ),
    isPending: false,
  };
}

function resolvingCompleteMutation(data: Partial<WarehouseDocument>) {
  return {
    mutate: vi.fn(
      (
        _payload: { id: string; data?: unknown },
        opts?: {
          onSuccess?: (data?: WarehouseDocument) => void;
          onError?: (err: unknown) => void;
        },
      ) => {
        opts?.onSuccess?.(data as unknown as WarehouseDocument);
      },
    ),
    isPending: false,
  };
}

function stubMutation() {
  return { mutate: vi.fn(), isPending: false };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useDocumentActions confirm toast", () => {
  it("shows the pendingApproval toast when confirm parks the document", () => {
    const { result } = renderHook(
      () =>
        useDocumentActions({
          docId: "doc-1",
          duplicateMutation: { mutateAsync: vi.fn() },
          confirmMutation: resolvingMutation({ status: "PENDING_APPROVAL" }),
          postNowMutation: stubMutation(),
          completeMutation: stubMutation(),
          cancelMutation: stubMutation(),
          deleteMutation: stubMutation(),
          undoMutation: stubMutation(),
        }),
      { wrapper },
    );

    act(() => {
      result.current.setConfirmAction("confirm");
    });
    act(() => {
      result.current.handleAction();
    });

    expect(toast.success).toHaveBeenCalledWith("Document sent for approval");
    expect(toast.success).not.toHaveBeenCalledWith(
      "Document confirmed — ready for execution",
    );
  });

  it("shows the confirmed toast when the document is actually confirmed", () => {
    const { result } = renderHook(
      () =>
        useDocumentActions({
          docId: "doc-1",
          duplicateMutation: { mutateAsync: vi.fn() },
          confirmMutation: resolvingMutation({ status: "CONFIRMED" }),
          postNowMutation: stubMutation(),
          completeMutation: stubMutation(),
          cancelMutation: stubMutation(),
          deleteMutation: stubMutation(),
          undoMutation: stubMutation(),
        }),
      { wrapper },
    );

    act(() => {
      result.current.setConfirmAction("confirm");
    });
    act(() => {
      result.current.handleAction();
    });

    expect(toast.success).toHaveBeenCalledWith(
      "Document confirmed — ready for execution",
    );
  });

  it("uses the cancelled toast for the cancel action regardless of status", () => {
    const { result } = renderHook(
      () =>
        useDocumentActions({
          docId: "doc-1",
          duplicateMutation: { mutateAsync: vi.fn() },
          confirmMutation: resolvingMutation({ status: "PENDING_APPROVAL" }),
          postNowMutation: stubMutation(),
          completeMutation: stubMutation(),
          cancelMutation: resolvingMutation({ status: "CANCELLED" }),
          deleteMutation: stubMutation(),
          undoMutation: stubMutation(),
        }),
      { wrapper },
    );

    act(() => {
      result.current.setConfirmAction("cancel");
    });
    act(() => {
      result.current.handleAction();
    });

    expect(toast.success).toHaveBeenCalledWith("Document cancelled");
    expect(toast.success).not.toHaveBeenCalledWith(
      "Document sent for approval",
    );
  });
});

describe("useDocumentActions server error surfacing", () => {
  it("surfaces the backend session-active message in the toast", () => {
    const backendMsg =
      "This document cannot be completed or cancelled while 1 active WMS receiving session(s) are in progress. Complete or cancel them first.";
    const { result } = renderHook(
      () =>
        useDocumentActions({
          docId: "doc-1",
          duplicateMutation: { mutateAsync: vi.fn() },
          confirmMutation: stubMutation(),
          postNowMutation: stubMutation(),
          completeMutation: rejectingCompleteMutation({
            code: "WMS_SESSION_ACTIVE",
            message: backendMsg,
          }),
          cancelMutation: stubMutation(),
          deleteMutation: stubMutation(),
          undoMutation: stubMutation(),
        }),
      { wrapper },
    );

    act(() => {
      result.current.handleComplete({
        lines: [{ line_id: "l1", done_quantity: 1 }],
      });
    });

    expect(toast.error).toHaveBeenCalledWith(backendMsg);
    expect(toast.error).not.toHaveBeenCalledWith("errors.completeFailed");
  });
});

describe("useDocumentActions backorder toast", () => {
  it("shows a backorder toast with a view action when complete spawns one", () => {
    const { result } = renderHook(
      () =>
        useDocumentActions({
          docId: "doc-1",
          duplicateMutation: { mutateAsync: vi.fn() },
          confirmMutation: stubMutation(),
          postNowMutation: stubMutation(),
          completeMutation: resolvingCompleteMutation({
            generated_backorder_id: "bo-1",
            generated_backorder_number: "PZ/2026/002",
          }),
          cancelMutation: stubMutation(),
          deleteMutation: stubMutation(),
          undoMutation: stubMutation(),
        }),
      { wrapper },
    );

    act(() => {
      result.current.handleComplete({
        lines: [{ line_id: "l1", done_quantity: 1 }],
      });
    });

    expect(toast.success).toHaveBeenCalledWith(
      "Document completed. Backorder PZ/2026/002 created for the remaining quantities.",
      expect.objectContaining({
        action: expect.objectContaining({ label: "View backorder" }),
      }),
    );
    expect(toast.success).not.toHaveBeenCalledWith(
      "Document completed — stock updated",
    );
  });

  it("shows the plain completed toast when no backorder was created", () => {
    const { result } = renderHook(
      () =>
        useDocumentActions({
          docId: "doc-1",
          duplicateMutation: { mutateAsync: vi.fn() },
          confirmMutation: stubMutation(),
          postNowMutation: stubMutation(),
          completeMutation: resolvingCompleteMutation({
            generated_backorder_id: null,
          }),
          cancelMutation: stubMutation(),
          deleteMutation: stubMutation(),
          undoMutation: stubMutation(),
        }),
      { wrapper },
    );

    act(() => {
      result.current.handleComplete({
        lines: [{ line_id: "l1", done_quantity: 5 }],
      });
    });

    expect(toast.success).toHaveBeenCalledWith(
      "Document completed — stock updated",
    );
  });
});

function resolvingUndoMutation(data: Partial<WarehouseDocument>) {
  return {
    mutate: vi.fn(
      (
        _id: string,
        opts?: {
          onSuccess?: (data?: WarehouseDocument) => void;
          onError?: (err: unknown) => void;
        },
      ) => {
        opts?.onSuccess?.(data as unknown as WarehouseDocument);
      },
    ),
    isPending: false,
  };
}

function rejectingUndoMutation(message: string) {
  const axiosLike = {
    isAxiosError: true,
    response: { data: { detail: { code: "VALIDATION_ERROR", message } } },
  };
  return {
    mutate: vi.fn(
      (
        _id: string,
        opts?: {
          onSuccess?: (data?: WarehouseDocument) => void;
          onError?: (err: unknown) => void;
        },
      ) => {
        opts?.onError?.(axiosLike);
      },
    ),
    isPending: false,
  };
}

describe("useDocumentActions undo", () => {
  it("offers Undo on the success toast of a posted receipt", () => {
    const undoMutation = stubMutation();
    const { result } = renderHook(
      () =>
        useDocumentActions({
          docId: "doc-1",
          duplicateMutation: { mutateAsync: vi.fn() },
          confirmMutation: stubMutation(),
          postNowMutation: stubMutation(),
          completeMutation: resolvingCompleteMutation({
            id: "doc-1",
            type: "IN",
            status: "COMPLETED",
            generated_backorder_id: null,
          }),
          cancelMutation: stubMutation(),
          deleteMutation: stubMutation(),
          undoMutation,
        }),
      { wrapper },
    );

    act(() => {
      result.current.handleComplete({
        lines: [{ line_id: "l1", done_quantity: 5 }],
      });
    });

    const options = vi.mocked(toast.success).mock.calls[0][1] as {
      action: { label: string; onClick: () => void };
    };
    expect(options.action.label).toBe("Undo receipt");
    act(() => options.action.onClick());
    expect(undoMutation.mutate).toHaveBeenCalledWith(
      "doc-1",
      expect.any(Object),
    );
  });

  it("says what the reversal is when the undo lands", () => {
    const { result } = renderHook(
      () =>
        useDocumentActions({
          docId: "doc-1",
          duplicateMutation: { mutateAsync: vi.fn() },
          confirmMutation: stubMutation(),
          postNowMutation: stubMutation(),
          completeMutation: stubMutation(),
          cancelMutation: stubMutation(),
          deleteMutation: stubMutation(),
          undoMutation: resolvingUndoMutation({
            id: "rev-1",
            number: "COR/2026/007",
            status: "COMPLETED",
          }),
        }),
      { wrapper },
    );

    act(() => result.current.setConfirmAction("undo"));
    act(() => result.current.handleAction());

    expect(toast.success).toHaveBeenCalledWith(
      "Undone — reversal COR/2026/007 is in the history",
      expect.objectContaining({
        action: expect.objectContaining({ label: "View reversal" }),
      }),
    );
  });

  it("points a refused undo at the correction form", () => {
    const onOpenCorrection = vi.fn();
    const { result } = renderHook(
      () =>
        useDocumentActions({
          docId: "doc-1",
          duplicateMutation: { mutateAsync: vi.fn() },
          confirmMutation: stubMutation(),
          postNowMutation: stubMutation(),
          completeMutation: stubMutation(),
          cancelMutation: stubMutation(),
          deleteMutation: stubMutation(),
          undoMutation: rejectingUndoMutation(
            "This cannot be undone: later movements used the stock it posted. Use Correct to change what is left instead.",
          ),
          onOpenCorrection,
        }),
      { wrapper },
    );

    act(() => result.current.setConfirmAction("undo"));
    act(() => result.current.handleAction());

    const options = vi.mocked(toast.error).mock.calls[0][1] as {
      action: { label: string; onClick: () => void };
    };
    expect(options.action.label).toBe("Correct");
    act(() => options.action.onClick());
    expect(onOpenCorrection).toHaveBeenCalledTimes(1);
  });
});
