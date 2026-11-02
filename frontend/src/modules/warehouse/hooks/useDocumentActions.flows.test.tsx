import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { toast } from "sonner";
import { AxiosError } from "axios";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { warehouseDocument } from "@/test/factories/documents";
import { downloadDocumentPdf } from "@/modules/warehouse/lib/downloadDocumentPdf";
import { useDocumentActions } from "./useDocumentActions";

// Where Execute leads asks the picking session; these tests are about the
// actions, so no session is open.
vi.mock("@/modules/warehouse/hooks/useDocumentScanSession", () => ({
  useDocumentScanSession: () => ({ data: null, isPending: false }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const navigate = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));

vi.mock("@/modules/warehouse/lib/downloadDocumentPdf", () => ({
  downloadDocumentPdf: vi.fn(() => Promise.resolve()),
}));

/** A 4xx refusal carrying the server's sentence, as axios hands it over. */
function refusal(detail: string): AxiosError {
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, {}, {
    status: 409,
    data: { detail },
  } as never);
}

type ToastAction = { label: string; onClick: () => void };

/** The action a toast offered, from the options of its nth call. */
function toastAction(mock: Mock, call = 0): ToastAction | undefined {
  const options = mock.mock.calls[call]?.[1] as
    { action?: ToastAction } | undefined;
  return options?.action;
}

function setup(
  over: { doc?: WarehouseDocument; onOpenCorrection?: () => void } = {},
) {
  const m = {
    duplicate: vi.fn(),
    confirm: vi.fn(),
    postNow: vi.fn(),
    complete: vi.fn(),
    cancel: vi.fn(),
    remove: vi.fn(),
    undo: vi.fn(),
  };
  const shape = (mutate: Mock) => ({ mutate, isPending: false });
  const utils = renderHook(() =>
    useDocumentActions({
      docId: "doc-1",
      doc: over.doc,
      docStatus: over.doc?.status,
      duplicateMutation: { mutateAsync: m.duplicate },
      confirmMutation: shape(m.confirm),
      postNowMutation: shape(m.postNow),
      completeMutation: shape(m.complete),
      cancelMutation: shape(m.cancel),
      deleteMutation: shape(m.remove),
      undoMutation: shape(m.undo),
      onOpenCorrection: over.onOpenCorrection,
    }),
  );
  return { m, utils };
}

function runConfirmed(
  utils: ReturnType<typeof setup>["utils"],
  action: "confirm" | "cancel" | "delete" | "undo" | "postNow",
) {
  act(() => utils.result.current.setConfirmAction(action));
  act(() => utils.result.current.handleAction());
}

/**
 * The detail page's confirm dialog hands every irreversible step to this
 * hook. These catch a step that writes to the wrong mutation, a delete that
 * leaves the reader on a page that no longer exists, a refusal that is
 * swallowed instead of spoken, and toast links that lead nowhere.
 */
describe("useDocumentActions — the confirm dialog's steps", () => {
  beforeEach(() => vi.clearAllMocks());

  it("does nothing when no step was chosen", () => {
    const { m, utils } = setup();
    act(() => utils.result.current.handleAction());
    expect(m.confirm).not.toHaveBeenCalled();
    expect(m.cancel).not.toHaveBeenCalled();
    expect(m.remove).not.toHaveBeenCalled();
  });

  it("confirms through the confirm mutation and closes the dialog", () => {
    const { m, utils } = setup();
    runConfirmed(utils, "confirm");
    expect(m.confirm).toHaveBeenCalledWith("doc-1", expect.any(Object));
    act(() => m.confirm.mock.calls[0][1].onSuccess({ status: "CONFIRMED" }));
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(utils.result.current.confirmAction).toBeNull();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("says a confirm parked the document for approval, not that it is ready", () => {
    const { m, utils } = setup();
    runConfirmed(utils, "confirm");
    act(() =>
      m.confirm.mock.calls[0][1].onSuccess({ status: "PENDING_APPROVAL" }),
    );
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringMatching(/approval/i),
    );
  });

  it("cancels through the cancel mutation and speaks the refusal", () => {
    const { m, utils } = setup();
    runConfirmed(utils, "cancel");
    expect(m.cancel).toHaveBeenCalledWith("doc-1", expect.any(Object));
    act(() => m.cancel.mock.calls[0][1].onError(refusal("Already shipped")));
    expect(toast.error).toHaveBeenCalledWith("Already shipped");
    expect(utils.result.current.confirmAction).toBeNull();
  });

  it("takes the reader back to the list once the document is deleted", () => {
    const { m, utils } = setup();
    runConfirmed(utils, "delete");
    expect(m.remove).toHaveBeenCalledWith("doc-1", expect.any(Object));
    act(() => m.remove.mock.calls[0][1].onSuccess());
    expect(navigate).toHaveBeenCalledWith("/warehouse");
  });

  it("posts nothing more after a one-step posting is refused, and says why", () => {
    const { m, utils } = setup();
    runConfirmed(utils, "postNow");
    act(() => m.postNow.mock.calls[0][1].onError(refusal("Not enough stock")));
    expect(toast.error).toHaveBeenCalledWith("Not enough stock");
    expect(utils.result.current.confirmAction).toBeNull();
  });
});

describe("useDocumentActions — undo answers with the reversal", () => {
  beforeEach(() => vi.clearAllMocks());

  it("links the toast to the reversal the server wrote", () => {
    const { m, utils } = setup();
    runConfirmed(utils, "undo");
    expect(m.undo).toHaveBeenCalledWith("doc-1", expect.any(Object));
    expect(utils.result.current.confirmAction).toBeNull();
    act(() =>
      m.undo.mock.calls[0][1].onSuccess({
        id: "rev-1",
        number: "KOR/1",
        status: "COMPLETED",
      }),
    );
    const action = toastAction(vi.mocked(toast.success));
    expect(action).toBeDefined();
    action?.onClick();
    expect(navigate).toHaveBeenCalledWith("/warehouse/documents/rev-1");
  });

  it("says a reversal waits for approval instead of claiming it is done", () => {
    const { m, utils } = setup();
    runConfirmed(utils, "undo");
    act(() =>
      m.undo.mock.calls[0][1].onSuccess({
        id: "rev-1",
        number: "KOR/1",
        status: "PENDING_APPROVAL",
      }),
    );
    expect(toastAction(vi.mocked(toast.success))).toBeUndefined();
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("KOR/1"),
    );
  });

  it("offers the correction form when the server refuses the undo", () => {
    const onOpenCorrection = vi.fn();
    const { m, utils } = setup({ onOpenCorrection });
    runConfirmed(utils, "undo");
    act(() => m.undo.mock.calls[0][1].onError(refusal("Stock was used up")));
    expect(toast.error).toHaveBeenCalledWith(
      "Stock was used up",
      expect.objectContaining({ action: expect.any(Object) }),
    );
    toastAction(vi.mocked(toast.error))?.onClick();
    expect(onOpenCorrection).toHaveBeenCalledTimes(1);
  });
});

describe("useDocumentActions — what a completion leaves behind", () => {
  beforeEach(() => vi.clearAllMocks());

  it("links the toast to the backorder a short receipt created", () => {
    const { m, utils } = setup();
    act(() => utils.result.current.handleComplete({}));
    act(() =>
      m.complete.mock.calls[0][1].onSuccess({
        id: "doc-1",
        status: "COMPLETED",
        type: "IN",
        generated_backorder_id: "bo-1",
        generated_backorder_number: "PZ/2",
      }),
    );
    toastAction(vi.mocked(toast.success))?.onClick();
    expect(navigate).toHaveBeenCalledWith("/warehouse/documents/bo-1");
  });

  it("offers Undo on the toast of a full posting, and the button reverses it", () => {
    const { m, utils } = setup();
    act(() => utils.result.current.handleComplete({}));
    act(() =>
      m.complete.mock.calls[0][1].onSuccess({
        id: "doc-1",
        status: "COMPLETED",
        type: "IN",
        reversed_by_id: null,
        generated_backorder_id: null,
      }),
    );
    toastAction(vi.mocked(toast.success))?.onClick();
    expect(m.undo).toHaveBeenCalledWith("doc-1", expect.any(Object));
  });

  it("confirms a correction before completing it, and says when confirming fails", () => {
    const { m, utils } = setup({
      doc: warehouseDocument({
        id: "doc-1",
        status: "DRAFT",
        type: "CORRECTION",
      }),
    });
    act(() => utils.result.current.handleApplyCorrection());
    act(() => m.confirm.mock.calls[0][1].onError(refusal("Locked period")));
    expect(toast.error).toHaveBeenCalledWith("Locked period");
    expect(m.complete).not.toHaveBeenCalled();
  });

  it("says the correction was applied once its completion lands", () => {
    const { m, utils } = setup({
      doc: warehouseDocument({
        id: "doc-1",
        status: "CONFIRMED",
        type: "CORRECTION",
      }),
    });
    act(() => utils.result.current.handleApplyCorrection());
    act(() => m.complete.mock.calls[0][1].onSuccess());
    expect(toast.success).toHaveBeenCalledTimes(1);
  });
});

describe("useDocumentActions — duplicate and PDF", () => {
  beforeEach(() => vi.clearAllMocks());

  it("takes the reader to the copy once it is made", async () => {
    const doc = warehouseDocument({ id: "doc-1" });
    const { m, utils } = setup({ doc });
    m.duplicate.mockResolvedValue({ id: "copy-1", number: "PZ/9" });
    await act(() => utils.result.current.handleDuplicate());
    expect(m.duplicate).toHaveBeenCalledWith("doc-1");
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("PZ/9"));
    expect(navigate).toHaveBeenCalledWith("/warehouse/documents/copy-1");
  });

  it("keeps the server's own words when the copy is refused", async () => {
    const { m, utils } = setup({ doc: warehouseDocument({ id: "doc-1" }) });
    m.duplicate.mockRejectedValue(refusal("You may not duplicate"));
    await act(() => utils.result.current.handleDuplicate());
    expect(toast.error).toHaveBeenCalledWith("You may not duplicate");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("copies nothing before the document has loaded", async () => {
    const { m, utils } = setup();
    await act(() => utils.result.current.handleDuplicate());
    expect(m.duplicate).not.toHaveBeenCalled();
  });

  it("builds the PDF from the document on the page", () => {
    const doc = warehouseDocument({ id: "doc-1" });
    const { utils } = setup({ doc });
    act(() => utils.result.current.handleDownloadPdf());
    expect(downloadDocumentPdf).toHaveBeenCalledWith(
      doc,
      expect.any(Function),
      expect.any(Function),
    );
  });
});
