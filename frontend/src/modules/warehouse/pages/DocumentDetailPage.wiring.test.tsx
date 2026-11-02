import { act, type ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PageHeaderData } from "@/hooks/useModulePageHeader";
import * as documentHooks from "@/modules/warehouse/hooks/useDocuments";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { documentLine, warehouseDocument } from "@/test/factories/documents";
import DocumentDetailPage from "./DocumentDetailPage";

/** The last props each stubbed child was rendered with. */
const seen = vi.hoisted(() => {
  const props: Record<string, Record<string, unknown>> = {};
  const stub = (name: string) => (p: Record<string, unknown>) => {
    props[name] = p;
    return null;
  };
  return { props, stub };
});

// Whether the Pack step is on the page: the real rule reads the picked lines.
const packing = vi.hoisted(() => ({ applies: false }));

const m = vi.hoisted(() => ({
  confirm: vi.fn(),
  postNow: vi.fn(),
  complete: vi.fn(),
  cancel: vi.fn(),
  remove: vi.fn(),
  undo: vi.fn(),
  update: vi.fn(),
  setLineTarget: vi.fn(),
  approve: vi.fn(),
  request: vi.fn(),
  // Answers like the factory's `mutate` on success: the options' onSuccess.
  requestMutate: vi.fn((_vars: unknown, options?: { onSuccess?: () => void }) =>
    options?.onSuccess?.(),
  ),
  reject: vi.fn(),
  header: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/hooks/useModulePageHeader", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useModulePageHeader")>()),
  useModulePageHeader: () => ({ setHeader: m.header }),
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["warehouse", "approvals"],
    isModuleEnabled: (name: string) =>
      ["warehouse", "approvals"].includes(name),
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  useDocument: vi.fn(),
  useDocumentCorrections: vi.fn(() => ({ data: [], isError: false })),
  useUpdateDocument: () => ({ mutate: m.update, isPending: false }),
  useDocumentWorkflow: () => ({
    confirmDocument: { mutate: m.confirm, isPending: false },
    postDocumentNow: { mutate: m.postNow, isPending: false },
    completeDocument: { mutate: m.complete, isPending: false },
    cancelDocument: { mutate: m.cancel, isPending: false },
    deleteDocument: { mutate: m.remove, isPending: false },
    undoDocument: { mutate: m.undo, isPending: false },
  }),
  useDuplicateDocument: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSetLineTarget: () => ({ mutate: m.setLineTarget, isPending: false }),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentApproval", () => ({
  useApproveDocument: () => ({ mutateAsync: m.approve, isPending: false }),
  useRequestDocumentApproval: () => ({
    mutateAsync: m.request,
    mutate: m.requestMutate,
    isPending: false,
  }),
  useRejectDocument: () => ({ mutateAsync: m.reject, isPending: false }),
  useDocumentApproval: () => ({ data: null }),
  useDocumentApprovalRequirement: () => ({
    data: { approval_required: false, workflow_configured: false },
  }),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({ data: undefined }),
}));
vi.mock("@/modules/warehouse/hooks/useDocumentPartnerOptions", () => ({
  useDocumentPartnerOptions: () => ({
    fieldProps: { partnersError: null, retryPartners: vi.fn() },
  }),
}));
vi.mock("@/modules/warehouse/hooks/useDocumentPlaces", () => ({
  useDocumentPlaceNames: () => ({}),
}));

// Every child the page hands a callback to is a stub that records its
// props: the test presses the callback and reads what the page did with it.
vi.mock("@/components/Slot", () => ({ TypedSlot: seen.stub("slot") }));
vi.mock("@/modules/warehouse/components/DocumentMetadataGrid", () => ({
  DocumentMetadataGrid: seen.stub("grid"),
}));
vi.mock("@/modules/warehouse/components/DocumentDetailModals", () => ({
  default: seen.stub("modals"),
}));
vi.mock("@/modules/warehouse/components/DocumentDetailLinesCard", () => ({
  DocumentDetailLinesCard: seen.stub("lines"),
}));
vi.mock("@/modules/warehouse/components/DocumentCorrectionsSection", () => ({
  DocumentCorrectionsSection: seen.stub("corrections"),
}));
vi.mock("@/modules/warehouse/components/DocumentScanSessionNotice", () => ({
  DocumentScanSessionNotice: seen.stub("session"),
}));
vi.mock("@/modules/warehouse/components/DocumentExecutionPanel", () => ({
  DocumentExecutionPanel: seen.stub("execution"),
}));
vi.mock("@/modules/warehouse/components/packing/DocumentPackingStep", () => ({
  DocumentPackingStep: seen.stub("packing"),
  PACKING_HASH: "#pack",
  usePackingStepShown: () => packing.applies,
}));
vi.mock("@/modules/warehouse/components/DocumentExecutionSection", () => ({
  DocumentExecutionSection: () => null,
}));
vi.mock("@/modules/warehouse/components/shipping/DocumentShipmentCard", () => ({
  DocumentShipmentCard: () => null,
}));
vi.mock("@/modules/warehouse/components/DocumentValueTotals", () => ({
  DocumentValueTotals: () => null,
}));
vi.mock("@/modules/warehouse/components/DocumentExtraCostsSection", () => ({
  DocumentExtraCostsSection: () => null,
}));
vi.mock("@/modules/warehouse/components/DocumentLineExtra", () => ({
  DocumentDetailExtra: () => null,
}));
vi.mock("@/modules/warehouse/components/DocumentStatusTimeline", () => ({
  DocumentStatusTimeline: () => null,
}));
vi.mock("@/components/ui/ReadOnlyNotice", () => ({
  ReadOnlyNotice: () => null,
}));

type Fn = (...args: unknown[]) => unknown;

/** A callback the page handed to a stubbed child, pressed inside act. */
function press(child: string, prop: string, ...args: unknown[]) {
  const fn = seen.props[child]?.[prop] as Fn | undefined;
  if (!fn) throw new Error(`${child} got no ${prop}`);
  let out: unknown;
  act(() => {
    out = fn(...args);
  });
  return out;
}

/** The header's action bar is an element the page builds; its callbacks are
 * pressed the same way. */
function pressHeader(prop: string, ...args: unknown[]) {
  const calls = m.header.mock.calls;
  const data = calls[calls.length - 1][0] as PageHeaderData;
  const actions = data.actions as ReactElement<Record<string, Fn>>;
  act(() => {
    actions.props[prop](...args);
  });
}

function modals() {
  return seen.props.modals as Record<string, unknown>;
}

function refusal(detail: string): AxiosError {
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, {}, {
    status: 409,
    data: { detail },
  } as never);
}

function givenDocument(over: Partial<WarehouseDocument> = {}) {
  const doc = warehouseDocument({
    id: "doc-1",
    type: "IN",
    number: "PZ/2026/001",
    status: "DRAFT",
    notes: "Leave at the back door",
    lines: [documentLine({ id: "line-1", document_id: "doc-1" })],
    ...over,
  });
  vi.mocked(documentHooks.useDocument).mockReturnValue({
    data: doc,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof documentHooks.useDocument>);
  return doc;
}

function renderPage() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/warehouse/documents/doc-1"]}>
        <Routes>
          <Route
            path="/warehouse/documents/:id"
            element={<DocumentDetailPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * The detail page is a hub of callbacks: the header's buttons, the metadata
 * grid, the lines, the modals. These tests press each callback the page
 * hands down and check the page did the one thing it promised — opened the
 * right modal, asked the right question, or wrote through the right
 * mutation with the right arguments. A button wired to the wrong state, a
 * dialog that confirms the wrong step, or a notes edit that writes on every
 * blur fails here.
 */
describe("DocumentDetailPage — header actions open what they name", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const key of Object.keys(seen.props)) delete seen.props[key];
  });

  it("opens the edit form, and closes it again", () => {
    givenDocument();
    renderPage();
    expect(modals().editOpen).toBe(false);
    pressHeader("onEdit");
    expect(modals().editOpen).toBe(true);
    press("modals", "onEditClose");
    expect(modals().editOpen).toBe(false);
  });

  it("asks before confirming, and the answer confirms this document", () => {
    givenDocument();
    renderPage();
    pressHeader("onConfirm");
    expect(modals().confirmAction).toBe("confirm");
    expect(modals().confirmVariant).toBe("default");
    expect(modals().confirmTitle).not.toBe("");
    press("modals", "onConfirmAction");
    expect(m.confirm).toHaveBeenCalledWith("doc-1", expect.any(Object));
  });

  it("asks before posting in one step, and the answer posts this draft", () => {
    givenDocument();
    renderPage();
    pressHeader("onPostNow");
    expect(modals().confirmAction).toBe("postNow");
    press("modals", "onConfirmAction");
    expect(m.postNow).toHaveBeenCalledWith({ id: "doc-1" }, expect.any(Object));
  });

  it("marks cancel and delete as dangerous, and backing out asks nothing", () => {
    givenDocument();
    renderPage();
    pressHeader("onCancel");
    expect(modals().confirmAction).toBe("cancel");
    expect(modals().confirmVariant).toBe("danger");
    pressHeader("onDelete");
    expect(modals().confirmAction).toBe("delete");
    expect(modals().confirmVariant).toBe("danger");
    press("modals", "onConfirmCancel");
    expect(modals().confirmAction).toBeNull();
    expect(m.remove).not.toHaveBeenCalled();
  });

  it("asks before undoing a completed receipt", () => {
    givenDocument({ status: "COMPLETED" });
    renderPage();
    pressHeader("onUndo");
    expect(modals().confirmAction).toBe("undo");
    press("modals", "onConfirmAction");
    expect(m.undo).toHaveBeenCalledWith("doc-1", expect.any(Object));
  });

  it("opens the return form and closes it", () => {
    givenDocument({ status: "COMPLETED" });
    renderPage();
    pressHeader("onReturn");
    expect(modals().returnOpen).toBe(true);
    press("modals", "onReturnClose");
    expect(modals().returnOpen).toBe(false);
  });

  it("opens the execution panel on a confirmed document and submits what was done", () => {
    givenDocument({ status: "CONFIRMED" });
    renderPage();
    expect(seen.props.execution).toBeUndefined();
    pressHeader("onExecute");
    expect(seen.props.execution).toBeDefined();
    const payload = { lines: [{ line_id: "line-1", quantity: "1" }] };
    press("execution", "onSubmit", payload);
    expect(m.complete).toHaveBeenCalledWith(
      { id: "doc-1", data: payload },
      expect.any(Object),
    );
  });

  it("leads Execute to the Pack step of a picked dispatch instead of a second panel", () => {
    packing.applies = true;
    try {
      givenDocument({ status: "CONFIRMED" });
      renderPage();
      pressHeader("onExecute");
      expect(seen.props.execution).toBeUndefined();
    } finally {
      packing.applies = false;
    }
  });

  it("folds the execution panel away when the worker backs out", () => {
    givenDocument({ status: "CONFIRMED" });
    renderPage();
    pressHeader("onExecute");
    const onCancel = seen.props.execution.onCancel as () => void;
    delete seen.props.execution;
    act(() => onCancel());
    expect(seen.props.execution).toBeUndefined();
    expect(m.complete).not.toHaveBeenCalled();
  });
});

describe("DocumentDetailPage — the floor flows close the document they ran on", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const key of Object.keys(seen.props)) delete seen.props[key];
  });

  it("completes the dispatch with its shipment once picking finishes", () => {
    givenDocument({ type: "OUT", status: "CONFIRMED" });
    renderPage();
    pressHeader("onStartPicking");
    expect(modals().pickingOpen).toBe(true);
    const shipment = { carrier: "DPD", tracking_number: "123" };
    press("modals", "onPickingClose", true, shipment);
    expect(modals().pickingOpen).toBe(false);
    expect(m.complete).toHaveBeenCalledWith(
      { id: "doc-1", data: { shipment } },
      expect.any(Object),
    );
  });

  it("closes picking without completing when the picker walked away", () => {
    givenDocument({ type: "OUT", status: "CONFIRMED" });
    renderPage();
    pressHeader("onStartPicking");
    press("modals", "onPickingClose", false);
    expect(modals().pickingOpen).toBe(false);
    expect(m.complete).not.toHaveBeenCalled();
  });

  it("asks for approval from the picking sheet and says so", () => {
    givenDocument({ type: "OUT", status: "CONFIRMED" });
    renderPage();
    pressHeader("onStartPicking");
    const fn = seen.props.modals.onPickingRequestApproval as () => void;
    act(() => fn());
    expect(m.requestMutate).toHaveBeenCalledWith(
      { docId: "doc-1" },
      expect.any(Object),
    );
    expect(toast.success).toHaveBeenCalled();
    expect(modals().pickingOpen).toBe(false);
  });

  it("leaves a refused approval request to the factory's toast", () => {
    // The start-failure screen's button awaits nothing: an awaited
    // `mutateAsync` handed the refusal to no one. Through `mutate` with no
    // `onError` of its own, the factory says it.
    givenDocument({ type: "OUT", status: "CONFIRMED" });
    renderPage();
    pressHeader("onStartPicking");
    act(() => (seen.props.modals.onPickingRequestApproval as () => void)());
    act(() => (seen.props.modals.onReceivingRequestApproval as () => void)());
    for (const [, options] of m.requestMutate.mock.calls) {
      expect(options).not.toHaveProperty("onError");
    }
    expect(m.requestMutate).toHaveBeenCalledTimes(2);
    expect(m.request).not.toHaveBeenCalled();
  });

  it("completes the receipt payload-free once receiving finishes", () => {
    givenDocument({ type: "IN", status: "CONFIRMED" });
    renderPage();
    pressHeader("onStartReceiving");
    expect(modals().receivingOpen).toBe(true);
    press("modals", "onReceivingClose", true);
    expect(modals().receivingOpen).toBe(false);
    expect(m.complete).toHaveBeenCalledWith(
      { id: "doc-1", data: undefined },
      expect.any(Object),
    );
  });

  it("asks for approval from the receiving sheet and closes it", () => {
    givenDocument({ type: "IN", status: "CONFIRMED" });
    renderPage();
    pressHeader("onStartReceiving");
    const fn = seen.props.modals.onReceivingRequestApproval as () => void;
    act(() => fn());
    expect(m.requestMutate).toHaveBeenCalledWith(
      { docId: "doc-1" },
      expect.any(Object),
    );
    expect(modals().receivingOpen).toBe(false);
  });

  it("resumes an open scanning session in the sheet it belongs to", () => {
    givenDocument({ type: "IN", status: "CONFIRMED" });
    renderPage();
    press("session", "onResumeReceiving");
    expect(modals().receivingOpen).toBe(true);
    press("session", "onResumePicking");
    expect(modals().pickingOpen).toBe(true);
  });
});

describe("DocumentDetailPage — edits write once, through the document", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const key of Object.keys(seen.props)) delete seen.props[key];
  });

  it("saves trimmed notes on blur and says it saved", () => {
    givenDocument();
    renderPage();
    press("grid", "onNotesChange", "  Ring twice  ");
    press("grid", "onNotesBlur");
    expect(m.update).toHaveBeenCalledWith(
      { id: "doc-1", data: { notes: "Ring twice" } },
      expect.any(Object),
    );
    const opts = m.update.mock.calls[0][1] as { onSuccess: () => void };
    act(() => opts.onSuccess());
    expect(toast.success).toHaveBeenCalled();
    expect(seen.props.grid.notesEditValue).toBeNull();
  });

  it("writes nothing when the notes did not change, or were never touched", () => {
    givenDocument();
    renderPage();
    press("grid", "onNotesBlur");
    press("grid", "onNotesChange", "Leave at the back door ");
    press("grid", "onNotesBlur");
    expect(m.update).not.toHaveBeenCalled();
    expect(seen.props.grid.notesEditValue).toBeNull();
  });

  it("sends emptied notes as null and speaks the refusal", () => {
    givenDocument();
    renderPage();
    press("grid", "onNotesChange", "   ");
    press("grid", "onNotesBlur");
    expect(m.update).toHaveBeenCalledWith(
      { id: "doc-1", data: { notes: null } },
      expect.any(Object),
    );
    const opts = m.update.mock.calls[0][1] as { onError: (e: unknown) => void };
    act(() => opts.onError(refusal("Document is locked")));
    expect(toast.error).toHaveBeenCalledWith("Document is locked");
  });

  it("clears the partner on an empty choice and reports both outcomes", () => {
    givenDocument();
    renderPage();
    press("grid", "onPartnerChange", "");
    expect(m.update).toHaveBeenCalledWith(
      { id: "doc-1", data: { partner_id: null } },
      expect.any(Object),
    );
    const opts = m.update.mock.calls[0][1] as {
      onSuccess: () => void;
      onError: (e: unknown) => void;
    };
    act(() => opts.onSuccess());
    expect(toast.success).toHaveBeenCalled();
    act(() => opts.onError(refusal("Partner archived")));
    expect(toast.error).toHaveBeenCalledWith("Partner archived");
  });

  it("sets a partner by its id", () => {
    givenDocument();
    renderPage();
    press("grid", "onPartnerChange", "partner-7");
    expect(m.update).toHaveBeenCalledWith(
      { id: "doc-1", data: { partner_id: "partner-7" } },
      expect.any(Object),
    );
  });

  it("moves one line's target through the line-target mutation", () => {
    givenDocument();
    renderPage();
    press("lines", "onLineTargetChange", "line-1", "loc-9");
    expect(m.setLineTarget).toHaveBeenCalledWith({
      docId: "doc-1",
      lineId: "line-1",
      targetLocationId: "loc-9",
    });
  });
});

describe("DocumentDetailPage — corrections, approvals and failures", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const key of Object.keys(seen.props)) delete seen.props[key];
  });

  it("opens the correction form from a completed document's corrections", () => {
    givenDocument({ status: "COMPLETED" });
    renderPage();
    press("corrections", "onNewCorrection");
    expect(modals().correctionOpen).toBe(true);
    press("modals", "onCorrectionClose");
    expect(modals().correctionOpen).toBe(false);
  });

  it("names a correction reason in words, not as its code", () => {
    givenDocument({ status: "COMPLETED" });
    renderPage();
    const format = seen.props.corrections.formatReason as (c: string) => string;
    expect(format("WRONG_QUANTITY")).toBe("Wrong quantity");
  });

  it("routes the slot's approve, request and reject through the document", async () => {
    givenDocument({ status: "CONFIRMED" });
    renderPage();
    const slot = seen.props.slot as {
      data: {
        onApprove: (id: string, notes?: string) => Promise<void>;
        onRequest: () => Promise<void>;
        onReject: (id: string, notes?: string) => Promise<void>;
      };
    };
    await act(() => slot.data.onApprove("req-1", "fine"));
    await act(() => slot.data.onRequest());
    await act(() => slot.data.onReject("req-1", "too much"));
    expect(m.approve).toHaveBeenCalledWith({ docId: "doc-1", notes: "fine" });
    expect(m.request).toHaveBeenCalledWith({ docId: "doc-1" });
    expect(m.reject).toHaveBeenCalledWith({
      docId: "doc-1",
      notes: "too much",
    });
  });

  it("offers a retry when the document could not be read", async () => {
    const refetch = vi.fn();
    vi.mocked(documentHooks.useDocument).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new AxiosError("Network Error", "ERR_NETWORK"),
      refetch,
    } as unknown as ReturnType<typeof documentHooks.useDocument>);
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
