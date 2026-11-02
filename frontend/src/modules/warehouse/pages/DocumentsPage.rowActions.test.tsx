import { act, type ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import type { PageHeaderData } from "@/hooks/useModulePageHeader";
import * as documentsHooks from "@/modules/warehouse/hooks/useDocuments";
import { useDocumentsList } from "@/modules/warehouse/hooks/useDocumentsList";
import { documentRow, warehouseDocument } from "@/test/factories/documents";
import DocumentsPage from "./DocumentsPage";

/** The last props each stubbed child was rendered with. */
const seen = vi.hoisted(() => {
  const props: Record<string, Record<string, unknown>> = {};
  const stub = (name: string) => (p: Record<string, unknown>) => {
    props[name] = p;
    return null;
  };
  return { props, stub };
});

const m = vi.hoisted(() => ({
  navigate: vi.fn(),
  header: vi.fn(),
  confirm: vi.fn(),
  cancel: vi.fn(),
  remove: vi.fn(),
  duplicate: vi.fn(),
  clearSelection: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => m.navigate,
}));

vi.mock("@/hooks/useModulePageHeader", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useModulePageHeader")>()),
  useModulePageHeader: () => ({ setHeader: m.header }),
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

vi.mock("@/modules/warehouse/hooks/useDocumentsList", () => ({
  useDocumentsList: vi.fn(),
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  useDocument: vi.fn(() => ({ data: undefined, isError: false })),
  useDocumentWorkflow: () => ({
    confirmDocument: { mutate: m.confirm, isPending: false },
    cancelDocument: { mutate: m.cancel, isPending: false },
    deleteDocument: { mutate: m.remove, isPending: false },
  }),
  useDuplicateDocument: () => ({ mutateAsync: m.duplicate, isPending: false }),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentBulkActions", () => ({
  useDocumentBulkActions: () => ({
    selectedIds: new Set<string>(),
    selectedDrafts: [],
    toggleSelect: vi.fn(),
    toggleSelectAll: vi.fn(),
    clearSelection: m.clearSelection,
    barProps: {},
    bulkConfirmOpen: false,
    setBulkConfirmOpen: vi.fn(),
    bulkDeleteOpen: false,
    setBulkDeleteOpen: vi.fn(),
    handleBulkConfirm: vi.fn(),
    handleBulkDelete: vi.fn(),
  }),
}));

vi.mock("@/components/ui/ReadOnlyNotice", () => ({
  ReadOnlyNotice: () => null,
}));
vi.mock("@/modules/warehouse/components/DocumentListItem", () => ({
  DocumentListItem: (p: Record<string, unknown>) => {
    const doc = p.doc as { id: string };
    seen.props[`row-${doc.id}`] = p;
    return null;
  },
}));
vi.mock("@/modules/warehouse/components/DocumentsFilters", () => ({
  DocumentsFilters: seen.stub("filters"),
}));
vi.mock("@/modules/warehouse/components/BulkActionBar", () => ({
  BulkActionBar: seen.stub("bulkBar"),
}));
vi.mock("@/modules/warehouse/components/NewDocumentMenu", () => ({
  NewDocumentMenu: seen.stub("newMenu"),
}));
vi.mock("@/modules/warehouse/components/DocumentsGettingStarted", () => ({
  DocumentsGettingStarted: seen.stub("gettingStarted"),
}));
vi.mock("@/modules/warehouse/components/DocumentFormModal", () => ({
  default: (p: Record<string, unknown>) => {
    seen.props[p.document ? "editForm" : "createForm"] = p;
    return null;
  },
}));
vi.mock("@/modules/warehouse/components/OpeningStockImportModal", () => ({
  default: seen.stub("openingStock"),
}));
vi.mock("@/modules/warehouse/components/picking/WmsPickingView", () => ({
  default: seen.stub("picking"),
}));
vi.mock("@/modules/partners/components/PartnerFilterBanner", () => ({
  PartnerFilterBanner: () => null,
}));

type Fn = (...args: unknown[]) => unknown;

function press(child: string, prop: string, ...args: unknown[]) {
  const fn = seen.props[child]?.[prop] as Fn | undefined;
  if (!fn) throw new Error(`${child} got no ${prop}`);
  let out: unknown;
  act(() => {
    out = fn(...args);
  });
  return out;
}

function refusal(detail: string): AxiosError {
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, {}, {
    status: 409,
    data: { detail },
  } as never);
}

const draft = documentRow(
  warehouseDocument({ id: "doc-1", number: "PZ/1", status: "DRAFT" }),
);

function givenList(over: Record<string, unknown> = {}) {
  const list = {
    documents: [draft],
    isLoading: false,
    skip: 0,
    limit: 25,
    total: 1,
    isNarrowed: false,
    clearFilters: vi.fn(),
    onPrev: vi.fn(),
    onNext: vi.fn(),
    onPageChange: vi.fn(),
    onLimitChange: vi.fn(),
    isError: false,
    refetch: vi.fn(),
    partnerId: null,
    clearPartnerFilter: vi.fn(),
    moduleColumns: [],
    ...over,
  };
  vi.mocked(useDocumentsList).mockReturnValue(
    list as unknown as ReturnType<typeof useDocumentsList>,
  );
  return list;
}

function headerActions(): ReactElement {
  const calls = m.header.mock.calls;
  return (calls[calls.length - 1][0] as PageHeaderData).actions as ReactElement;
}

/**
 * The list's rows, header and modals hand callbacks to each other. These
 * tests press each one and check the page did what the row asked: opened
 * the right document, asked before a destructive step and wrote through the
 * matching mutation, spoke a refusal, or closed the sheet it opened. A row
 * action wired to the wrong mutation, a dialog that cannot be backed out
 * of, or an edit that opens no form fails here.
 */
describe("DocumentsPage — what a row asks for", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const key of Object.keys(seen.props)) delete seen.props[key];
  });

  it("opens the document a row names", () => {
    givenList();
    render(<DocumentsPage />);
    press("row-doc-1", "onOpenDetails", "doc-1");
    expect(m.navigate).toHaveBeenCalledWith("/warehouse/documents/doc-1");
  });

  it("asks before deleting, and the answer deletes that row's document", async () => {
    givenList();
    const user = userEvent.setup();
    render(<DocumentsPage />);
    press("row-doc-1", "onRequestAction", "delete", draft);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(m.remove).toHaveBeenCalledWith("doc-1", expect.any(Object));
    const opts = m.remove.mock.calls[0][1] as { onSuccess: () => void };
    act(() => opts.onSuccess());
    expect(toast.success).toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("speaks the server's refusal of a confirm and closes the question", async () => {
    givenList();
    const user = userEvent.setup();
    render(<DocumentsPage />);
    press("row-doc-1", "onRequestAction", "confirm", draft);
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(m.confirm).toHaveBeenCalledWith("doc-1", expect.any(Object));
    const opts = m.confirm.mock.calls[0][1] as {
      onError: (e: unknown) => void;
    };
    act(() => opts.onError(refusal("No lines to confirm")));
    expect(toast.error).toHaveBeenCalledWith("No lines to confirm");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("lets the reader back out of a cancel without writing", async () => {
    givenList();
    const user = userEvent.setup();
    render(<DocumentsPage />);
    press("row-doc-1", "onRequestAction", "cancel", draft);
    await screen.findByRole("alertdialog");
    // The confirm and the dismiss are both "Cancel" here; Escape is the way
    // out that cannot be mistaken for the step itself.
    await user.keyboard("{Escape}");
    expect(m.cancel).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("reads the whole document before opening the edit form, and closes it", () => {
    givenList();
    const full = warehouseDocument({ id: "doc-1" });
    vi.mocked(documentsHooks.useDocument).mockImplementation(
      (id?: string) =>
        ({
          data: id === "doc-1" ? full : undefined,
          isError: false,
        }) as unknown as ReturnType<typeof documentsHooks.useDocument>,
    );
    render(<DocumentsPage />);
    expect(seen.props.editForm).toBeUndefined();
    press("row-doc-1", "onEdit", draft);
    expect(seen.props.editForm?.document).toBe(full);
    const close = seen.props.editForm.onClose as () => void;
    delete seen.props.editForm;
    act(() => close());
    expect(seen.props.editForm).toBeUndefined();
  });

  it("drops the edit and says why when the document cannot be read", () => {
    givenList();
    vi.mocked(documentsHooks.useDocument).mockImplementation(
      (id?: string) =>
        ({
          data: undefined,
          isError: id === "doc-1",
          error: refusal("Document is gone"),
        }) as unknown as ReturnType<typeof documentsHooks.useDocument>,
    );
    render(<DocumentsPage />);
    press("row-doc-1", "onEdit", draft);
    expect(toast.error).toHaveBeenCalledWith("Document is gone");
  });

  it("reopens a row's picking session over that document alone, and clears the selection on close", () => {
    givenList();
    render(<DocumentsPage />);
    press("row-doc-1", "onResumePicking", "doc-1");
    expect(seen.props.picking).toMatchObject({
      documentId: "doc-1",
      documentIds: ["doc-1"],
    });
    press("picking", "onClose");
    expect(m.clearSelection).toHaveBeenCalledTimes(1);
  });
});

describe("DocumentsPage — header, empty list and failures", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const key of Object.keys(seen.props)) delete seen.props[key];
  });

  it("opens the opening-stock import from the header and closes it", async () => {
    givenList();
    const user = userEvent.setup();
    render(<DocumentsPage />);
    render(headerActions());
    await user.click(screen.getByRole("button", { name: /opening stock/i }));
    expect(seen.props.openingStock).toBeDefined();
    const close = seen.props.openingStock.onClose as () => void;
    delete seen.props.openingStock;
    act(() => close());
    expect(seen.props.openingStock).toBeUndefined();
  });

  it("creates the type chosen from the menu and opens what was created", () => {
    givenList();
    const { rerender } = render(<DocumentsPage />);
    const menu = headerActions();
    render(menu);
    press("newMenu", "onSelect", "OUT");
    rerender(<DocumentsPage />);
    expect(seen.props.createForm).toMatchObject({ initialType: "OUT" });
    press("createForm", "onCreated", { id: "doc-9" });
    expect(m.navigate).toHaveBeenCalledWith("/warehouse/documents/doc-9");
    const close = seen.props.createForm.onClose as () => void;
    delete seen.props.createForm;
    act(() => close());
    expect(seen.props.createForm).toBeUndefined();
  });

  it("starts the first document as a receipt from the empty list", () => {
    givenList({ documents: [], total: 0 });
    render(<DocumentsPage />);
    press("gettingStarted", "onCreateFirst");
    expect(seen.props.createForm).toMatchObject({ initialType: "IN" });
  });

  it("offers to ask again when the list could not be read", async () => {
    const list = givenList({ documents: [], isError: true });
    const user = userEvent.setup();
    render(<DocumentsPage />);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(list.refetch).toHaveBeenCalledTimes(1);
  });
});
