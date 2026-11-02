import React, { act, useState } from "react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@/test/utils";
import { toast } from "sonner";
import { documentsApi } from "@/modules/warehouse/api/documents";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import DocumentsPage from "./DocumentsPage";
import * as documentsHooks from "@/modules/warehouse/hooks/useDocuments";
import type {
  WarehouseDocument,
  WarehouseDocumentRow,
} from "@/modules/warehouse/types";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { scanWithHardwareScanner } from "@/test/scanner";
import { documentLine } from "@/test/factories/documents";
import { documentRow, warehouseDocument } from "@/test/factories/documents";
import { moduleRegistry } from "@/lib/moduleRegistry";

// This screen hides its actions from an account that cannot use them,
// so a spec about the actions has to say who is looking at them.
beforeEach(() => {
  signInWith(["warehouse:read", "warehouse:write"]);
});

afterEach(() => {
  signOut();
});

// Which modules the organization has on; the registry itself is the real one.
const enabled = vi.hoisted(() => ({ modules: [] as string[] }));
vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useEnabledModulesOptional: () => enabled.modules,
}));

moduleRegistry.register({
  name: "certs_demo",
  routes: [],
  documentColumnContributors: [
    {
      key: "certificate",
      label: "Certificate",
      hasValue: (d) => d.lines.some((l) => l.metaData.certs_demo?.number),
      render: (d) =>
        d.lines
          .map((l) => l.metaData.certs_demo?.number)
          .filter(Boolean)
          .join(", "),
    },
  ],
  documentFilterContributors: [{ key: "lapsing", label: "Lapsing soon" }],
});

const navigateMock = vi.hoisted(() => vi.fn());
const duplicateMutateAsyncMock = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );

  // The suite stubs `window.location`, so a real router never sees a write to
  // the address. The list keeps its filters in the search params; this keeps
  // them in component state so a chip click reaches the query.
  const { useState } = await vi.importActual<typeof import("react")>("react");
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useSearchParams: () => {
      const [params, setParams] = useState(() => new URLSearchParams());
      return [
        params,
        (
          next: URLSearchParams | ((prev: URLSearchParams) => URLSearchParams),
        ) => setParams(typeof next === "function" ? next(params) : next),
      ] as const;
    },
  };
});

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
  Toaster: () => null,
}));

vi.mock("@/modules/warehouse/components/DocumentFormModal", () => ({
  default: ({
    document,
    initialType,
  }: {
    document?: { id: string };
    initialType?: string | null;
  }) => (
    <div data-testid="document-form-modal">
      {document ? `edit-${document.id}` : `new-${initialType}`}
    </div>
  ),
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  useDocuments: vi.fn(),
  // The edit form reads the whole document; the row has no lines.
  useDocument: vi.fn(() => ({ data: undefined })),
  useDocumentWorkflow: vi.fn(() => ({
    confirmDocument: { mutate: vi.fn(), isPending: false },
    postDocumentNow: { mutate: vi.fn(), isPending: false },
    completeDocument: { mutate: vi.fn(), isPending: false },
    cancelDocument: { mutate: vi.fn(), isPending: false },
    deleteDocument: { mutate: vi.fn(), isPending: false },
    undoDocument: { mutate: vi.fn(), isPending: false },
    isSavingDraft: false,
    isTransitionPending: false,
  })),
  useDuplicateDocument: vi.fn(() => ({
    mutateAsync: duplicateMutateAsyncMock,
    isPending: false,
  })),
}));

function HeaderHarness({ children }: { children: React.ReactNode }) {
  const [headerData, setHeaderData] = useState<PageHeaderData>({});

  return (
    <PageHeaderContext.Provider
      value={{ data: headerData, setHeader: setHeaderData }}
    >
      {headerData.actions ? <div>{headerData.actions}</div> : null}
      {children}
    </PageHeaderContext.Provider>
  );
}

async function renderWithHeader(ui: React.ReactElement) {
  let renderResult: ReturnType<typeof render> | undefined;

  await act(async () => {
    renderResult = render(<HeaderHarness>{ui}</HeaderHarness>);
  });

  return renderResult!;
}

function buildDocument(
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocument {
  return warehouseDocument({
    id: "doc-1",
    organization_id: "org-1",
    type: "IN",
    number: "PZ/2026/001",
    status: "DRAFT",
    partner_id: "partner-1",
    source_location_id: null,
    target_location_id: "loc-2",
    scheduled_date: null,
    notes: "Inbound receipt",
    external_reference: "REF-1",
    created_by: "user-1",
    confirmed_by: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-04-01T10:00:00Z",
    confirmed_at: null,
    completed_at: null,
    lines: [
      documentLine({
        id: "line-1",
        document_id: "doc-1",
        item_id: null,
        product_template_id: null,
        name: "Widget",
        brand: null,
        barcode: null,
        quantity: "2",
        batch_number: null,
        expiry_date: null,
        notes: null,
        line_number: 1,
      }),
    ],
    ...overrides,
  });
}

// The list carries rows; a row is built from a whole document the way the
// server builds it, so a test still says what is on the document.
function buildRow(
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocumentRow {
  return documentRow(buildDocument(overrides));
}

describe("DocumentsPage", () => {
  const mockedUseDocuments = vi.mocked(documentsHooks.useDocuments);

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseDocuments.mockReturnValue({
      data: {
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
        has_more: false,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);
  });

  it("renders empty state and header create actions", async () => {
    const user = userEvent.setup();

    await renderWithHeader(<DocumentsPage />);

    // one "+ New document" menu on every width — the type options
    // live inside the popover now.
    const createButton = screen.getByRole("button", { name: "New document" });
    expect(createButton).toBeInTheDocument();

    await act(async () => {
      await user.click(createButton);
    });

    expect(
      screen.getByRole("menuitem", { name: "Receipt" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Delivery" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Transfer" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Get started with documents")).toBeInTheDocument();
  });

  it("opens the create modal from the empty-state CTA", async () => {
    const user = userEvent.setup();

    await renderWithHeader(<DocumentsPage />);

    const cta = screen.getByTestId("getting-started-cta");
    expect(cta).toHaveTextContent("Create your first document");

    await act(async () => {
      await user.click(cta);
    });

    await waitFor(() => {
      expect(screen.getByTestId("document-form-modal")).toHaveTextContent(
        "new-IN",
      );
    });
  });

  it("offers a reader no create CTA in the empty state", async () => {
    signInWith(["warehouse:read"]);

    await renderWithHeader(<DocumentsPage />);

    expect(screen.getByText("Get started with documents")).toBeInTheDocument();
    expect(screen.queryByTestId("getting-started-cta")).not.toBeInTheDocument();
  });

  it("leaves settings to the module bar instead of repeating it in the start tile", async () => {
    await renderWithHeader(<DocumentsPage />);

    expect(
      screen.queryByRole("link", { name: "Open documents settings" }),
    ).not.toBeInTheDocument();
  });

  it("opens create modal from header action", async () => {
    const user = userEvent.setup();

    await renderWithHeader(<DocumentsPage />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "New document" }));
    });
    await waitFor(() => {
      expect(
        screen.getByRole("menuitem", { name: "Receipt" }),
      ).toBeInTheDocument();
    });
    await act(async () => {
      await user.click(screen.getByRole("menuitem", { name: "Receipt" }));
    });

    await waitFor(() => {
      expect(screen.getByTestId("document-form-modal")).toHaveTextContent(
        "new-IN",
      );
    });
  });

  it("opens edit modal for a draft document", async () => {
    const user = userEvent.setup();
    vi.mocked(documentsHooks.useDocument).mockReturnValue({
      data: buildDocument(),
    } as unknown as ReturnType<typeof documentsHooks.useDocument>);

    mockedUseDocuments.mockReturnValue({
      data: {
        items: [buildRow()],
        total: 1,
        limit: 50,
        offset: 0,
        has_more: false,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    await renderWithHeader(<DocumentsPage />);

    expect(screen.getAllByText("PZ/2026/001").length).toBeGreaterThan(0);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "More actions" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Edit" }));
    });

    await waitFor(() => {
      expect(screen.getByTestId("document-form-modal")).toHaveTextContent(
        "edit-doc-1",
      );
    });
  });

  it("passes search text to the documents query", async () => {
    const user = userEvent.setup();

    mockedUseDocuments.mockReturnValue({
      data: {
        items: [buildRow()],
        total: 1,
        limit: 50,
        offset: 0,
        has_more: false,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    await renderWithHeader(<DocumentsPage />);

    const searchInputs = screen.getAllByRole("textbox");
    await act(async () => {
      await user.type(searchInputs[0], "PO-SEARCH");
    });

    await waitFor(() => {
      expect(mockedUseDocuments).toHaveBeenLastCalledWith(
        expect.objectContaining({
          search: "PO-SEARCH",
        }),
      );
    });
  });

  it("passes discrepancy code filter to the documents query", async () => {
    const user = userEvent.setup();

    mockedUseDocuments.mockReturnValue({
      data: {
        items: [buildRow()],
        total: 1,
        limit: 50,
        offset: 0,
        has_more: false,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    await renderWithHeader(<DocumentsPage />);

    // the select lives behind the filter button now (desktop bar +
    // mobile toggle both exist in jsdom — either opens the same panel).
    await act(async () => {
      await user.click(screen.getAllByRole("button", { name: /Filter/ })[0]);
    });
    await act(async () => {
      await user.selectOptions(
        // desktop + mobile panels share one state — pick the first instance
        screen.getAllByLabelText("Discrepancy Code")[0],
        "SHORTAGE",
      );
    });

    await waitFor(() => {
      expect(mockedUseDocuments).toHaveBeenLastCalledWith(
        expect.objectContaining({
          discrepancy_code: "SHORTAGE",
        }),
      );
    });
  });

  it("passes PENDING_APPROVAL status filter to the documents query", async () => {
    const user = userEvent.setup();

    // One document, because the filter bar is not offered over an untouched
    // empty list — there is nothing there to narrow.
    mockedUseDocuments.mockReturnValue({
      data: {
        items: [buildRow()],
        total: 1,
        limit: 50,
        offset: 0,
        has_more: false,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    await renderWithHeader(<DocumentsPage />);

    await act(async () => {
      await user.click(screen.getByTestId("filter-PENDING_APPROVAL"));
    });

    await waitFor(() => {
      expect(mockedUseDocuments).toHaveBeenLastCalledWith(
        expect.objectContaining({
          status: "PENDING_APPROVAL",
        }),
      );
    });
  });

  it("duplicates a document from the list and opens the new draft", async () => {
    const user = userEvent.setup();

    mockedUseDocuments.mockReturnValue({
      data: {
        items: [buildRow()],
        total: 1,
        limit: 50,
        offset: 0,
        has_more: false,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);
    duplicateMutateAsyncMock.mockResolvedValue({
      id: "dup-1",
      number: "PZ/2026/002",
    });

    await renderWithHeader(<DocumentsPage />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "More actions" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Duplicate" }));
    });

    await waitFor(() => {
      expect(duplicateMutateAsyncMock).toHaveBeenCalledWith("doc-1");
      expect(navigateMock).toHaveBeenCalledWith("/warehouse/documents/dup-1");
    });
  });

  it("routes confirmed documents to the detail execution workflow", async () => {
    const user = userEvent.setup();

    mockedUseDocuments.mockReturnValue({
      data: {
        items: [
          buildRow({
            id: "doc-confirmed-1",
            status: "CONFIRMED",
            confirmed_at: "2026-04-02T12:00:00Z",
          }),
        ],
        total: 1,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    await renderWithHeader(<DocumentsPage />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "More actions" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Execute" }));
    });

    expect(navigateMock).toHaveBeenCalledWith(
      "/warehouse/documents/doc-confirmed-1",
    );
  });
  it("offers the document types as a menu a keyboard can drive", async () => {
    // The trigger opened a Popover full of plain buttons: a screen reader
    // announced "buttons in a group", and arrow keys did nothing.
    const user = userEvent.setup();

    await renderWithHeader(<DocumentsPage />);

    const trigger = screen.getByRole("button", { name: "New document" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");

    await act(async () => {
      await user.click(trigger);
    });

    const menu = screen.getByRole("menu");
    const items = screen.getAllByRole("menuitem");
    expect(menu).toBeInTheDocument();
    expect(items).toHaveLength(6);

    items[0].focus();
    await act(async () => {
      await user.keyboard("{ArrowDown}");
    });
    expect(items[1]).toHaveFocus();

    await act(async () => {
      await user.keyboard("{ArrowUp}");
    });
    expect(items[0]).toHaveFocus();
  });

  it("puts a checkbox on every row instead of a mode that reveals them", async () => {
    // "Select all" and a "Select" button sat side by side under near-identical
    // names; the mode's only job was to unhide the row checkboxes, while
    // select-all worked whether or not it was on.
    mockedUseDocuments.mockReturnValue({
      data: {
        items: [buildRow(), buildRow({ id: "doc-2", number: "PZ/2026/002" })],
        total: 2,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    await renderWithHeader(<DocumentsPage />);

    // One per row plus the select-all in the header row.
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
    expect(
      screen.queryByRole("button", { name: /^Select$/ }),
    ).not.toBeInTheDocument();
  });

  it("names the export file after the reader's own day", async () => {
    // The filename is a day the reader reads, so it has to be the reader's
    // day: `toISOString()` answers in UTC, which is yesterday or tomorrow
    // for most of the planet around midnight.
    const user = userEvent.setup();
    mockedUseDocuments.mockReturnValue({
      data: {
        items: [buildRow()],
        total: 1,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    await renderWithHeader(<DocumentsPage />);

    const rowCheckbox = screen.getAllByRole("checkbox")[1];
    await act(async () => {
      await user.click(rowCheckbox);
    });

    const originalTZ = process.env.TZ;
    process.env.TZ = "Europe/Warsaw";
    vi.useFakeTimers();
    // 00:30 on 11 September 2026 local is still 22:30 on the 10th in UTC.
    vi.setSystemTime(new Date(2026, 8, 11, 0, 30));
    let filename = "";
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        filename = this.download;
      });
    const originalCreateObjectUrl = globalThis.URL.createObjectURL;
    const originalRevokeObjectUrl = globalThis.URL.revokeObjectURL;
    globalThis.URL.createObjectURL = () => "blob:documents";
    globalThis.URL.revokeObjectURL = () => {};
    try {
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));

      expect(filename).toBe("documents_export_2026-09-11.csv");
    } finally {
      clickSpy.mockRestore();
      globalThis.URL.createObjectURL = originalCreateObjectUrl;
      globalThis.URL.revokeObjectURL = originalRevokeObjectUrl;
      vi.useRealTimers();
      process.env.TZ = originalTZ;
    }
  });

  it("selects a single row without turning any mode on first", async () => {
    const user = userEvent.setup();
    mockedUseDocuments.mockReturnValue({
      data: {
        items: [buildRow(), buildRow({ id: "doc-2", number: "PZ/2026/002" })],
        total: 2,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    await renderWithHeader(<DocumentsPage />);

    const rowCheckbox = screen.getAllByRole("checkbox")[1];
    await act(async () => {
      await user.click(rowCheckbox);
    });

    expect(rowCheckbox).toBeChecked();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
  });

  describe("Pick selected", () => {
    const dispatch = (n: number, over: Partial<WarehouseDocument> = {}) =>
      buildRow({
        id: `out-${n}`,
        type: "OUT",
        status: "CONFIRMED",
        number: `WZ/2026/00${n}`,
        ...over,
      });

    const list = (...docs: WarehouseDocumentRow[]) =>
      mockedUseDocuments.mockReturnValue({
        data: { items: docs, total: docs.length },
        isLoading: false,
      } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    it("starts one session over the confirmed dispatches that are ticked", async () => {
      const user = userEvent.setup();
      let body: unknown = null;
      server.use(
        http.post("/api/v1/warehouse/picking/start", async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({
            id: "s-1",
            document_id: "out-1",
            status: "active",
            lines: [],
            documents: [],
            total_lines: 0,
            picked_lines: 0,
            pending_lines: 0,
            shelf_scan_required: false,
          });
        }),
      );
      list(
        dispatch(1),
        dispatch(2),
        buildRow({ id: "draft-1", number: "PZ/2026/009" }),
      );

      await renderWithHeader(<DocumentsPage />);
      // Select all: the draft is ticked too and must be left out of the start.
      await act(async () => {
        await user.click(screen.getByRole("checkbox", { name: "Select all" }));
      });
      await act(async () => {
        await user.click(
          screen.getByRole("button", { name: "Pick 2 selected" }),
        );
      });

      await waitFor(() =>
        expect(body).toEqual({ document_ids: ["out-1", "out-2"] }),
      );
    });

    it("shows the sentence the backend refused the start with", async () => {
      const user = userEvent.setup();
      server.use(
        http.post("/api/v1/warehouse/picking/start", () =>
          HttpResponse.json(
            { detail: "Document WZ/2026/002 is already being picked." },
            { status: 409 },
          ),
        ),
      );
      list(dispatch(1), dispatch(2));

      await renderWithHeader(<DocumentsPage />);
      await act(async () => {
        await user.click(screen.getByRole("checkbox", { name: "Select all" }));
      });
      await act(async () => {
        await user.click(
          screen.getByRole("button", { name: "Pick 2 selected" }),
        );
      });

      expect(
        await screen.findByText(
          "Document WZ/2026/002 is already being picked.",
        ),
      ).toBeInTheDocument();
    });

    it("keeps a single ticked dispatch on the single-document start", async () => {
      const user = userEvent.setup();
      let singleStarts = 0;
      server.use(
        http.post("/api/v1/warehouse/documents/out-1/picking/start", () => {
          singleStarts += 1;
          return HttpResponse.json({ detail: "stop here" }, { status: 409 });
        }),
      );
      list(dispatch(1), dispatch(2));

      await renderWithHeader(<DocumentsPage />);
      await act(async () => {
        await user.click(screen.getAllByRole("checkbox")[1]);
      });
      await act(async () => {
        await user.click(
          screen.getByRole("button", { name: "Pick 1 selected" }),
        );
      });

      await waitFor(() => expect(singleStarts).toBe(1));
    });

    it("keeps a scan for the open session out of the register search", async () => {
      const user = userEvent.setup();
      let scanned: unknown = null;
      const pickLine = {
        id: "l1",
        document_line_id: "dl-1",
        document_id: "out-1",
        document_number: "WZ/2026/001",
        pick_order: 1,
        status: "pending",
        picked_quantity: 0,
        bin_location: "A-01",
        product_name: "Widget",
        lot_name: null,
        expected_quantity: 1,
        uom_symbol: "pcs",
      };
      server.use(
        http.post("/api/v1/warehouse/documents/out-1/picking/start", () =>
          HttpResponse.json({
            id: "s-1",
            document_id: "out-1",
            status: "active",
            lines: [pickLine],
            documents: [],
            total_lines: 1,
            picked_lines: 0,
            pending_lines: 1,
            shelf_scan_required: false,
          }),
        ),
        http.post(
          "/api/v1/warehouse/documents/out-1/picking/s-1/scan",
          async ({ request }) => {
            scanned = await request.json();
            return HttpResponse.json({});
          },
        ),
      );
      list(dispatch(1));

      await renderWithHeader(<DocumentsPage />);
      await act(async () => {
        await user.click(screen.getByRole("checkbox", { name: "Select all" }));
      });
      await act(async () => {
        await user.click(
          screen.getByRole("button", { name: "Pick 1 selected" }),
        );
      });
      await screen.findByText("Widget");

      act(() => {
        scanWithHardwareScanner("5907777000002", document.body);
      });

      await waitFor(() => expect(scanned).not.toBeNull());
      expect(mockedUseDocuments).not.toHaveBeenCalledWith(
        expect.objectContaining({ search: "5907777000002" }),
      );
      expect(screen.getByText("Widget")).toBeInTheDocument();
    });

    it("offers nothing to pick when only drafts or receipts are ticked", async () => {
      const user = userEvent.setup();
      list(buildRow(), dispatch(2, { type: "IN" }));

      await renderWithHeader(<DocumentsPage />);
      await act(async () => {
        await user.click(screen.getByRole("checkbox", { name: "Select all" }));
      });

      expect(screen.getByText("2 selected")).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /^Pick \d+ selected$/ }),
      ).not.toBeInTheDocument();
    });
  });

  describe("a session left open when its sheet was closed", () => {
    const openOver = (over: Partial<WarehouseDocument>) =>
      buildRow({
        status: "CONFIRMED",
        work_stage: "in_progress",
        next_action: "resume",
        stage_holder_name: "Ann",
        ...over,
      });

    const openDispatch = () =>
      openOver({
        id: "out-9",
        type: "OUT",
        number: "WZ/2026/009",
      });

    const listOne = (doc: WarehouseDocumentRow) =>
      mockedUseDocuments.mockReturnValue({
        data: { items: [doc], total: 1 },
        isLoading: false,
      } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    it("marks the row and reopens that session rather than starting a second", async () => {
      const user = userEvent.setup();
      let startedFrom: string | null = null;
      server.use(
        http.post(
          "/api/v1/warehouse/documents/:documentId/picking/start",
          ({ params }) => {
            startedFrom = `/api/v1/warehouse/documents/${params.documentId}/picking/start`;
            return HttpResponse.json({
              id: "s-open",
              document_id: "out-9",
              status: "paused",
              lines: [],
              documents: [],
              total_lines: 0,
              picked_lines: 0,
              pending_lines: 0,
              shelf_scan_required: false,
            });
          },
        ),
      );
      listOne(openDispatch());

      await renderWithHeader(<DocumentsPage />);

      expect(screen.getByText("In progress · Ann")).toBeInTheDocument();

      await act(async () => {
        await user.click(screen.getByRole("button", { name: "More actions" }));
      });
      await act(async () => {
        await user.click(screen.getByRole("button", { name: "Resume" }));
      });

      await waitFor(() =>
        expect(startedFrom).toBe(
          "/api/v1/warehouse/documents/out-9/picking/start",
        ),
      );
    });

    it("keeps the picking resume off a receipt whose receiving session is open", async () => {
      // The stage is direction-neutral — a receipt being received reads
      // *in progress* just like a dispatch being picked — while the menu's
      // resume always opens the picking sheet, which the server refuses for
      // a type it does not handle. The row may say the session is open; it
      // may not offer a door that cannot take the reader into it.
      const user = userEvent.setup();
      let starts = 0;
      server.use(
        http.post(
          "/api/v1/warehouse/documents/:documentId/picking/start",
          () => {
            starts += 1;
            return HttpResponse.json({ detail: "stop here" }, { status: 400 });
          },
        ),
      );
      listOne(
        openOver({
          id: "in-4",
          type: "IN",
          number: "IN/2026/004",
        }),
      );

      await renderWithHeader(<DocumentsPage />);

      expect(screen.getByText("In progress · Ann")).toBeInTheDocument();

      await act(async () => {
        await user.click(screen.getByRole("button", { name: "More actions" }));
      });

      expect(
        screen.queryByRole("button", { name: "Resume" }),
      ).not.toBeInTheDocument();
      expect(starts).toBe(0);
    });

    it("keeps the resume on a transfer, whose open session is a picking one", async () => {
      const user = userEvent.setup();
      let startedFrom: string | null = null;
      server.use(
        http.post(
          "/api/v1/warehouse/documents/:documentId/picking/start",
          ({ params }) => {
            startedFrom = `/api/v1/warehouse/documents/${params.documentId}/picking/start`;
            return HttpResponse.json({
              id: "s-transfer",
              document_id: "int-1",
              status: "paused",
              lines: [],
              documents: [],
              total_lines: 0,
              picked_lines: 0,
              pending_lines: 0,
              shelf_scan_required: false,
            });
          },
        ),
      );
      listOne(
        openOver({
          id: "int-1",
          type: "INT",
          number: "MM/2026/001",
        }),
      );

      await renderWithHeader(<DocumentsPage />);

      await act(async () => {
        await user.click(screen.getByRole("button", { name: "More actions" }));
      });
      await act(async () => {
        await user.click(screen.getByRole("button", { name: "Resume" }));
      });

      await waitFor(() =>
        expect(startedFrom).toBe(
          "/api/v1/warehouse/documents/int-1/picking/start",
        ),
      );
    });
  });

  it("names what the list could not ask for, and offers to ask again", async () => {
    // "An error occurred" answered a question the reader had not asked:
    // which of the page's reads went unanswered is what tells them whether
    // to retry or to go look elsewhere.
    const refetch = vi.fn();
    mockedUseDocuments.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("network down"),
      refetch,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    await renderWithHeader(<DocumentsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Failed to load documents",
    );

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalled();
  });

  describe("bulk confirm and print", () => {
    const rows = (...docs: WarehouseDocumentRow[]) =>
      mockedUseDocuments.mockReturnValue({
        data: { items: docs, total: docs.length },
        isLoading: false,
      } as unknown as ReturnType<typeof documentsHooks.useDocuments>);

    it("confirms the selected drafts once and names every refusal", async () => {
      const user = userEvent.setup();
      const confirmMutate = vi.fn(
        (
          id: string,
          opts?: { onSuccess?: () => void; onError?: (e: unknown) => void },
        ) =>
          id === "d2"
            ? opts?.onError?.(
                Object.assign(new Error("x"), {
                  response: {
                    status: 422,
                    data: { detail: "Not enough stock" },
                  },
                  isAxiosError: true,
                }),
              )
            : opts?.onSuccess?.(),
      );
      vi.mocked(documentsHooks.useDocumentWorkflow).mockReturnValue({
        confirmDocument: { mutate: confirmMutate, isPending: false },
        postDocumentNow: { mutate: vi.fn(), isPending: false },
        completeDocument: { mutate: vi.fn(), isPending: false },
        cancelDocument: { mutate: vi.fn(), isPending: false },
        deleteDocument: { mutate: vi.fn(), isPending: false },
        undoDocument: { mutate: vi.fn(), isPending: false },
        isSavingDraft: false,
        isTransitionPending: false,
      } as unknown as ReturnType<typeof documentsHooks.useDocumentWorkflow>);
      rows(
        buildRow({ id: "d1", number: "PZ/1" }),
        buildRow({ id: "d2", number: "PZ/2" }),
        buildRow({ id: "d3", number: "PZ/3" }),
      );

      await renderWithHeader(<DocumentsPage />);
      await act(async () => {
        await user.click(screen.getByRole("checkbox", { name: "Select all" }));
      });
      await act(async () => {
        await user.click(
          screen.getByRole("button", { name: "Confirm 3 drafts" }),
        );
      });
      const dialog = screen.getByRole("alertdialog");
      await act(async () => {
        await user.click(
          within(dialog).getByRole("button", { name: "Confirm 3 drafts" }),
        );
      });

      await waitFor(() => expect(confirmMutate).toHaveBeenCalledTimes(3));
      expect(toast.success).toHaveBeenCalledWith("Confirmed 2 drafts");
      const [title, options] = vi.mocked(toast.error).mock.calls[0];
      expect(title).toBe("1 draft was not confirmed");
      const summary = render(<>{options?.description as React.ReactNode}</>);
      expect(within(summary.container).getByRole("listitem")).toHaveTextContent(
        "PZ/2: Not enough stock",
      );
    });

    it("downloads the selected confirmed documents as one file in list order", async () => {
      const user = userEvent.setup();
      const downloadSpy = vi
        .spyOn(documentsApi, "downloadPdfBatch")
        .mockResolvedValue(new Blob(["%PDF"]));
      const originalCreate = globalThis.URL.createObjectURL;
      globalThis.URL.createObjectURL = () => "blob:pdf";
      const clickSpy = vi
        .spyOn(HTMLAnchorElement.prototype, "click")
        .mockImplementation(() => {});
      rows(
        buildRow({ id: "c1", number: "WZ/1", status: "CONFIRMED" }),
        buildRow({ id: "dr", number: "WZ/2", status: "DRAFT" }),
        buildRow({ id: "c3", number: "WZ/3", status: "COMPLETED" }),
      );
      try {
        await renderWithHeader(<DocumentsPage />);
        await act(async () => {
          await user.click(
            screen.getByRole("checkbox", { name: "Select all" }),
          );
        });
        await act(async () => {
          await user.click(
            screen.getByRole("button", { name: "Print 2 as one PDF" }),
          );
        });

        await waitFor(() =>
          expect(downloadSpy).toHaveBeenCalledWith(
            ["c1", "c3"],
            expect.any(String),
          ),
        );
        expect(clickSpy).toHaveBeenCalledTimes(1);
      } finally {
        downloadSpy.mockRestore();
        clickSpy.mockRestore();
        globalThis.URL.createObjectURL = originalCreate;
      }
    });
  });

  describe("what a module adds", () => {
    beforeEach(() => {
      enabled.modules = ["certs_demo"];
      mockedUseDocuments.mockReturnValue({
        data: {
          items: [
            buildRow({
              id: "certified",
              number: "PZ/2026/007",
              lines: [
                documentLine({
                  id: "line-c",
                  name: "Gouda Cheese",
                  meta_data: { certs_demo: { number: "C-17" } },
                }),
              ],
            }),
            buildRow({ id: "plain", number: "PZ/2026/008" }),
          ],
          total: 2,
          limit: 50,
          offset: 0,
          has_more: false,
        },
        isLoading: false,
      } as unknown as ReturnType<typeof documentsHooks.useDocuments>);
    });

    afterEach(() => {
      enabled.modules = [];
    });

    it("shows a module's value, named, on the rows it fills", async () => {
      await renderWithHeader(<DocumentsPage />);

      expect(screen.getByText("C-17")).toBeInTheDocument();
      // Only the row that has a certificate names the column.
      expect(screen.getAllByText("Certificate")).toHaveLength(1);
    });

    it("narrows the list on the server with a module's filter", async () => {
      const user = userEvent.setup();
      await renderWithHeader(<DocumentsPage />);
      expect(mockedUseDocuments).toHaveBeenLastCalledWith(
        expect.objectContaining({ module_filter: undefined }),
      );

      await act(async () => {
        await user.click(screen.getAllByRole("button", { name: /Filter/ })[0]);
      });
      await act(async () => {
        await user.click(
          screen.getAllByRole("button", { name: "Lapsing soon" })[0],
        );
      });
      expect(mockedUseDocuments).toHaveBeenLastCalledWith(
        expect.objectContaining({ module_filter: ["certs_demo:lapsing"] }),
      );

      await act(async () => {
        await user.click(
          screen.getAllByRole("button", { name: "Lapsing soon" })[0],
        );
      });
      expect(mockedUseDocuments).toHaveBeenLastCalledWith(
        expect.objectContaining({ module_filter: undefined }),
      );
    });

    it("adds nothing while the module is switched off", async () => {
      const user = userEvent.setup();
      enabled.modules = [];
      await renderWithHeader(<DocumentsPage />);
      await act(async () => {
        await user.click(screen.getAllByRole("button", { name: /Filter/ })[0]);
      });

      expect(screen.queryByText("C-17")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Lapsing soon" }),
      ).not.toBeInTheDocument();
    });
  });
});
