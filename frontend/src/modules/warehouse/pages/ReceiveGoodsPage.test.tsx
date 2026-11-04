/**
 * The one-screen receive: the order fills the sheet, the planner says where
 * each line goes, and one press posts the whole receipt.
 *
 * These tests pin the behaviour the screen was built for, not the layout:
 * choosing a supplier loads its open order, the filled counts travel to
 * `/warehouse/documents/post` with the order's prices and line ids, prices stay out of
 * the way until accounting asks for them, and the keyboard can do the whole
 * job — Enter through the counts and Ctrl+Enter to post.
 */
import { act, useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render as renderPlain } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useParams,
} from "react-router-dom";
import { AxiosError } from "axios";
import { fireEvent, render, screen, waitFor, within } from "@/test/utils";
import i18n from "@/i18n/config";
import * as modulesCtx from "@/contexts/ModulesContext";
import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";
import type { SlotDataMap } from "@/lib/moduleRegistry";
import { ReadableError } from "@/lib/errors";
import { useFormGuardStore } from "@/store/formGuardStore";
import { serveLocations } from "@/test/serveLocations";
import ReceiveGoodsPage from "./ReceiveGoodsPage";

const state = vi.hoisted(() => ({
  postNew: vi.fn(),
  createDraft: vi.fn(),
  confirm: vi.fn(),
  undo: vi.fn(),
  search: vi.fn(),
  importResult: {} as Record<string, unknown>,
  // What the page asked the locations endpoint for.
  locationRequests: [] as URLSearchParams[],
  // Whether the organization tracks the value of what it receives.
  valueShown: false,
}));

const rights = vi.hoisted(() => ({ write: true }));
const ordersHook = vi.hoisted(() => vi.fn());
const supplierHook = vi.hoisted(() => vi.fn());
const openReceiptsHook = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => rights.write,
  useCanManage: () => true,
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

vi.mock("@/hooks/usePartnerPicker", () => ({
  usePartnerPicker: () => ({
    options: [{ id: "partner-1", name: "Hurtownia Kowalski" }],
    setSearch: vi.fn(),
    loading: false,
    error: null,
    retry: vi.fn(),
    selectedOffered: true,
  }),
}));

vi.mock("@/hooks/useOpenPurchaseOrders", () => ({
  useOpenPurchaseOrders: ordersHook,
  useOrderSupplier: supplierHook,
  useOrderOpenReceipts: openReceiptsHook,
}));

// The catalogue a line typed by hand on the order is named from.
vi.mock("@/lib/api/productTemplateOptions", () => ({
  searchProductTemplates: vi.fn(async () => [
    { product_template_id: "tpl-dell", name: "Dell laptop" },
  ]),
  createProductTemplate: vi.fn(),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({
    data: { value_tracking_enabled: false, tax_handling: "NONE" },
  }),
}));

vi.mock("@/modules/warehouse/hooks/useShowDocumentValue", () => ({
  useShowDocumentValue: () => state.valueShown,
}));

vi.mock("@/modules/warehouse/hooks/useReceiptPlan", () => ({
  useReceiptPlan: () => ({
    plansByKey: {
      get: () => ({
        planned_location_id: "shelf-1",
        planned_location_name: "Shelf A",
        planned_source: "rule",
        planned_rule_match_key: "product_template",
        planned_rule_match_name: "Jasmine Rice",
        planned_rule_warning: null,
        planned_over_capacity: false,
        planned_capacity_used: null,
        planned_capacity_max: null,
        planned_shelf_fill: null,
      }),
    },
    isFetching: false,
    error: null,
  }),
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import("@/modules/warehouse/hooks/useDocuments")
    >();
  return {
    ...actual,
    usePostNewDocument: () => ({
      mutateAsync: state.postNew,
      isPending: false,
    }),
    useCreateDocument: () => ({
      mutateAsync: state.createDraft,
      isPending: false,
    }),
    useConfirmDocument: () => ({
      mutateAsync: state.confirm,
      isPending: false,
    }),
    useUndoDocument: () => ({
      mutate: state.undo,
      isPending: false,
    }),
  };
});

// The camera is a live device: a test hands the screen the code it read.
const camera = vi.hoisted(() => ({
  onCode: null as ((code: string) => void) | null,
}));

vi.mock("@/hooks/useScanCamera", () => ({
  useScanCamera: ({
    onCodeScanned,
  }: {
    onCodeScanned: (c: string) => void;
  }) => {
    camera.onCode = onCodeScanned;
    return {
      scannerError: null,
      isCameraActive: false,
      setIsCameraActive: vi.fn(),
      restartCamera: vi.fn(),
      toggleTorch: vi.fn(),
      isTorchOn: false,
    };
  },
}));

vi.mock("@/modules/warehouse/api/documents_products", () => ({
  documentsProductsApi: { productSearch: state.search },
}));

vi.mock("@/components/ui/SearchableCombobox", () => ({
  SearchableCombobox: ({
    id,
    label,
    value,
    options,
    onChange,
    placeholder,
    error,
    createLabel,
    onCreateNew,
    "aria-label": ariaLabel,
  }: {
    id?: string;
    error?: string;
    label?: string;
    "aria-label"?: string;
    value: string;
    options: Array<{ id: string; name: string }>;
    onChange: (id: string) => void;
    placeholder?: string;
    createLabel?: string;
    onCreateNew?: (query: string) => void;
  }) => (
    <label>
      {onCreateNew && (
        <span
          role="button"
          tabIndex={0}
          onClick={(event) => {
            event.preventDefault();
            onCreateNew("Palarnia Nowa");
          }}
        >
          {createLabel}
        </span>
      )}
      {label}
      <select
        id={id}
        aria-label={label ?? ariaLabel}
        aria-invalid={error ? true : undefined}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.name}
          </option>
        ))}
      </select>
      {/* A real picker reports a choice of the option it already holds; a
          select does not, so the stub offers that press as a button. */}
      <button type="button" onClick={() => onChange(value)}>
        {`Choose ${label ?? "option"} again`}
      </button>
    </label>
  ),
}));

vi.mock("@/modules/warehouse/components/DocumentImportModal", () => ({
  DocumentImportModal: ({
    onImported,
  }: {
    onImported: (result: Record<string, unknown>) => void;
  }) => (
    <button type="button" onClick={() => onImported(state.importResult)}>
      import-stub
    </button>
  ),
}));

function order() {
  return {
    id: "po-1",
    number: "PO/2026/002",
    currency: "PLN",
    lines: [
      {
        poId: "po-1",
        poNumber: "PO/2026/002",
        poCurrency: "PLN",
        poLineId: "pol-1",
        productTemplateId: "tpl-rice",
        name: "Jasmine Rice",
        outstanding: "40",
        ordered: "40",
        uomId: "uom-1",
        uomSymbol: "pcs",
        unitPrice: "6.20",
        taxRate: "23",
      },
    ],
  };
}

/** The same order with a second line the delivery may leave out. */
function twoLineOrder() {
  const first = order();
  return {
    ...first,
    lines: [
      ...first.lines,
      {
        ...first.lines[0],
        poLineId: "pol-2",
        productTemplateId: "tpl-sugar",
        name: "Cane Sugar",
        outstanding: "10",
        ordered: "10",
        uomId: "uom-sugar",
        unitPrice: "9.40",
      },
    ],
  };
}

function posted() {
  return {
    id: "doc-1",
    number: "PZ/2026/015",
    type: "IN",
    status: "COMPLETED",
    lines: [{ id: "line-1" }],
  };
}

/** The correction an undo writes against the receipt. */
function reversal() {
  return {
    id: "doc-cor-1",
    number: "COR/2026/001",
    type: "COR",
    status: "COMPLETED",
    lines: [],
  };
}

/** One row of a pasted sheet, as the import API answers it. */
function pastedRow(args: {
  id: string;
  quantity: string;
  batch?: string;
  expiry?: string;
  name?: string;
}) {
  return {
    id: args.id,
    name: args.name ?? "Jasmine Rice",
    quantity: args.quantity,
    product_template_id: "tpl-rice",
    item_id: null,
    uom_id: "uom-1",
    batch_number: args.batch ?? null,
    expiry_date: args.expiry ?? null,
    unit_price: null,
    tax_rate: null,
  };
}

function renderPage() {
  return render(<ReceiveGoodsPage />);
}

/** The page reached by a link, with the order's own screen behind it. */
function renderAt(url: string) {
  const queryClient = new QueryClient();
  return renderPlain(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[url]}>
        <I18nextProvider i18n={i18n}>
          <Routes>
            <Route path="/warehouse/receive" element={<ReceiveGoodsPage />} />
            <Route path="/purchase-orders/:id" element={<OrderStub />} />
            <Route path="/warehouse/documents/:id" element={<DocumentStub />} />
          </Routes>
        </I18nextProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function OrderStub() {
  const { id } = useParams();
  return <p>Order {id}</p>;
}

/** The receipt's page, with the hash that says which sheet it opens. */
function DocumentStub() {
  const { id } = useParams();
  const { hash } = useLocation();
  return <p>{`Document ${id}${hash}`}</p>;
}

/** A screen narrower than `sm`, as a phone in the hand is. */
function holdAPhone() {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === "(max-width: 639px)",
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("ReceiveGoodsPage", () => {
  it("offers only places that may hold stock, never another module's", async () => {
    // A receipt puts goods down: it asks for the stock slice, which leaves
    // a module's own places out whatever the general lists mix.
    renderPage();
    await waitFor(() =>
      expect(state.locationRequests.length).toBeGreaterThan(0),
    );
    for (const asked of state.locationRequests) {
      expect(asked.get("exclude_module_contexts")).toBe("true");
    }
  });

  it("adds a supplier that does not exist yet without leaving the form", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "+ Create new partner" }),
    );

    expect(
      await screen.findByDisplayValue("Palarnia Nowa"),
    ).toBeInTheDocument();
  });

  it("never reads the organization's locations whole", async () => {
    // A warehouse of thousands of shelves: the page asks for a couple of rows
    // to know whether there is a place to default to, and nothing more.
    state.locationRequests = serveLocations(
      Array.from({ length: 500 }, (_, i) => ({
        id: `shelf-${i}`,
        name: `Shelf ${i}`,
      })),
    );
    renderPage();
    await waitFor(() =>
      expect(state.locationRequests.length).toBeGreaterThan(0),
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    for (const asked of state.locationRequests) {
      expect(Number(asked.get("limit"))).toBeLessThanOrEqual(30);
      expect(asked.get("offset") ?? "0").toBe("0");
    }
  });

  beforeEach(() => {
    rights.write = true;
    state.valueShown = false;
    openReceiptsHook.mockReturnValue({
      receipts: [],
      error: null,
      isError: false,
      refetch: vi.fn(),
    });
    supplierHook.mockImplementation((orderId: string | null) => ({
      partnerId: orderId ? "partner-1" : null,
      isLoading: false,
      error: null,
    }));
    state.locationRequests = serveLocations([
      { id: "loc-1", name: "Main Warehouse" },
    ]);
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["warehouse", "partners"],
      isModuleEnabled: () => true,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    // The real hook asks only once a supplier is named; mirror that here, or
    // the sheet would pre-load an order the reader never chose.
    ordersHook.mockImplementation((partnerId: string | null) => ({
      orders: partnerId ? [order()] : [],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    }));
    state.postNew.mockReset().mockResolvedValue(posted());
    state.createDraft.mockReset();
    state.undo
      .mockReset()
      .mockImplementation(
        (_id: string, options?: { onSuccess?: (answer: unknown) => void }) =>
          options?.onSuccess?.(reversal()),
      );
    state.search.mockReset().mockImplementation((query: string) =>
      Promise.resolve(
        query.toLowerCase().includes("sugar")
          ? [
              {
                product_template_id: "tpl-sugar",
                item_id: null,
                name: "Cane Sugar",
                sku: "CS-1000",
                barcode: null,
                uom_id: "uom-sugar",
                uom_symbol: "pcs",
              },
            ]
          : [
              {
                product_template_id: "tpl-rice",
                item_id: null,
                name: "Jasmine Rice",
                sku: "JR-1000",
                barcode: null,
                uom_id: "uom-1",
                uom_symbol: "pcs",
              },
            ],
      ),
    );
    state.importResult = {
      imported: 1,
      matched: 1,
      unmatched: 0,
      stubs_created: 0,
      failed: 0,
      errors: [],
      no_stock: [],
      lines: [
        {
          id: "pasted-1",
          name: "Cane Sugar",
          quantity: "18",
          product_template_id: "tpl-sugar",
          item_id: null,
          uom_id: "uom-sugar",
          batch_number: null,
          expiry_date: null,
          unit_price: null,
          tax_rate: null,
        },
      ],
    };
  });

  it("loads the supplier's order lines as soon as the supplier is chosen", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(ordersHook).toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText("From"), "partner-1");

    expect(await screen.findByText("Jasmine Rice")).toBeInTheDocument();
    expect(screen.getAllByText(/40 pcs/).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("textbox", { name: /How many arrived: Jasmine Rice/ }),
    ).toHaveValue("40");
    expect(
      screen.getByText(/PO\/2026\/002 expects 1 line/),
    ).toBeInTheDocument();
    // The planner's answer and the reason are on the row before posting.
    expect(
      screen.getByText("→ Shelf A · rule: Jasmine Rice"),
    ).toBeInTheDocument();
  });

  it("receives a customer's return as a receipt naming the customer", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      screen.getByRole("radio", { name: /A customer's return/ }),
    );
    // The partner field now asks for the customer who sent the goods back.
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    expect(
      screen.getByLabelText("Customer's document number"),
    ).toBeInTheDocument();
    await user.type(
      screen.getByRole("combobox", { name: "Scan or search a product" }),
      "rice",
    );
    await user.keyboard("{Enter}");
    await screen.findByText("Jasmine Rice");

    await user.click(
      screen.getByRole("button", { name: "Receive the return" }),
    );

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
    const sent = state.postNew.mock.calls[0][0].data;
    expect(sent).toEqual(
      expect.objectContaining({ type: "IN", partner_id: "partner-1" }),
    );
    // A customer has no purchase orders waiting: none is looked for.
    expect(ordersHook).toHaveBeenLastCalledWith(null);
  });

  it("books an internal receipt without a partner and adds it to stock", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      screen.getByRole("radio", { name: /An internal receipt/ }),
    );

    // Nobody outside the company stands behind these goods: no partner field
    // and no supplier's document, only the shelf they are put on.
    expect(screen.queryByLabelText("From")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Supplier's document number"),
    ).not.toBeInTheDocument();

    await user.type(
      screen.getByRole("combobox", { name: "Scan or search a product" }),
      "rice",
    );
    await user.keyboard("{Enter}");
    await screen.findByText("Jasmine Rice");

    await user.click(screen.getByRole("button", { name: "Add to stock" }));

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
    const sent = state.postNew.mock.calls[0][0].data;
    expect(sent.type).toBe("INTERNAL_IN");
    expect(sent.partner_id).toBeUndefined();
  });

  it("receives a supplier's delivery chosen on the screen", async () => {
    const user = userEvent.setup();
    renderPage();

    // Start on another answer, so choosing the supplier is itself the act
    // under test rather than the sheet's default.
    await user.click(
      screen.getByRole("radio", { name: /An internal receipt/ }),
    );
    await user.click(screen.getByRole("radio", { name: /From a supplier/ }));

    // The supplier's sheet asks for the supplier and its open order again.
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");
    expect(
      screen.getByRole("textbox", { name: /How many arrived: Jasmine Rice/ }),
    ).toHaveValue("40");

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
    const sent = state.postNew.mock.calls[0][0].data;
    expect(sent).toEqual(
      expect.objectContaining({ type: "IN", partner_id: "partner-1" }),
    );
    expect(sent.lines[0]).toEqual(
      expect.objectContaining({
        product_template_id: "tpl-rice",
        expected_quantity: "40",
        source_po_line_id: "pol-1",
      }),
    );
  });

  it("keeps the counted receipt when the chosen source is pressed again", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    const quantity = screen.getByRole("textbox", {
      name: /How many arrived: Jasmine Rice/,
    });
    await user.clear(quantity);
    await user.type(quantity, "2");

    // The choice group reports a press on the answer already chosen too.
    // That is not a change of source: the supplier, the order and the count
    // the reader has just typed must survive it.
    await user.click(screen.getByRole("radio", { name: /From a supplier/ }));

    expect(screen.getByLabelText("From")).toHaveValue("partner-1");
    expect(
      screen.getByRole("textbox", { name: /How many arrived: Jasmine Rice/ }),
    ).toHaveValue("2");
    expect(
      screen.getByText(/PO\/2026\/002 expects 1 line/),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
    const sent = state.postNew.mock.calls[0][0].data;
    expect(sent).toEqual(
      expect.objectContaining({ type: "IN", partner_id: "partner-1" }),
    );
    expect(sent.lines[0]).toEqual(
      expect.objectContaining({
        expected_quantity: "2",
        source_po_line_id: "pol-1",
      }),
    );
  });

  it("keeps the order's lines when the supplier already chosen is chosen again", async () => {
    // The real hook hands back the same order object until its data moves.
    const waiting = order();
    ordersHook.mockImplementation((partnerId: string | null) => ({
      orders: partnerId ? [waiting] : [],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    }));
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    // The picker reports a choice of the value it already holds; the order
    // chosen for this supplier has not changed, so nothing reloads it.
    await user.click(
      screen.getByRole("button", { name: /^Choose From.* again$/ }),
    );

    expect(
      screen.getByRole("textbox", { name: /How many arrived: Jasmine Rice/ }),
    ).toHaveValue("40");
    expect(
      screen.getByText(/PO\/2026\/002 expects 1 line/),
    ).toBeInTheDocument();
  });

  it("drops the document number typed for the previous source", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(
      screen.getByLabelText("Supplier's document number"),
      "WZ-77",
    );

    await user.click(
      screen.getByRole("radio", { name: /A customer's return/ }),
    );

    expect(screen.getByLabelText("Customer's document number")).toHaveValue("");
  });

  it("fills the sheet from the supplier's orders as read now, not as they were cached", async () => {
    // The cached order still owes two lines while the read that follows
    // the choice is under way; the answer owes one. The sheet must carry
    // the answer, not the lines it showed first.
    const fresh = { current: false };
    ordersHook.mockImplementation((partnerId: string | null) => ({
      orders: !partnerId ? [] : [fresh.current ? order() : twoLineOrder()],
      isLoading: false,
      isFetching: Boolean(partnerId) && !fresh.current,
      error: null,
      refetch: vi.fn(),
    }));
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    expect(screen.queryByText("Cane Sugar")).not.toBeInTheDocument();

    fresh.current = true;
    await user.type(
      screen.getByLabelText("Supplier's document number"),
      "WZ-1",
    );

    expect(await screen.findByText("Jasmine Rice")).toBeInTheDocument();
    expect(screen.queryByText("Cane Sugar")).not.toBeInTheDocument();
    expect(
      screen.getByText(/PO\/2026\/002 expects 1 line/),
    ).toBeInTheDocument();
  });

  it("posts the whole receipt once, with the order's count, price and line id", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
    expect(state.postNew).toHaveBeenCalledWith({
      data: {
        type: "IN",
        partner_id: "partner-1",
        target_location_id: "loc-1",
        external_reference: undefined,
        lines: [
          expect.objectContaining({
            product_template_id: "tpl-rice",
            expected_quantity: "40",
            uom_id: "uom-1",
            source_po_line_id: "pol-1",
            unit_price: "6.20",
            tax_rate: "23",
          }),
        ],
      },
      // The press is named for the server, so a retry is answered with the
      // receipt the first send made instead of a second one.
      key: expect.any(String),
      // Nobody has been asked about a surplus yet.
      confirmSurplus: false,
    });
    // The shared result panel names the document the office got.
    expect(await screen.findByText("PZ/2026/015")).toBeInTheDocument();
    expect(screen.getByText(/Received 1 line/)).toBeInTheDocument();
  });

  it("lets the shelf be changed before posting", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    const lineShelf = screen.getByRole("combobox", { name: "Line location" });
    await within(lineShelf).findByRole("option", { name: "Main Warehouse" });
    await user.selectOptions(lineShelf, "loc-1");
    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
    expect(
      state.postNew.mock.calls[0][0].data.lines[0].target_location_id,
    ).toBe("loc-1");
  });

  it("keeps prices out of the way until accounting asks for them", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(screen.queryByText("Price / VAT")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Add prices for accounting" }),
    );
    expect(screen.getByText("Unit price")).toBeInTheDocument();
  });

  describe("a line with no price", () => {
    it("says before the post that it will carry no value", async () => {
      state.valueShown = true;
      const user = userEvent.setup();
      renderPage();
      await user.type(
        screen.getByRole("combobox", { name: "Scan or search a product" }),
        "rice",
      );
      await user.keyboard("{Enter}");
      await screen.findByRole("textbox", {
        name: /How many arrived: Jasmine Rice/,
      });

      expect(screen.getByRole("status")).toHaveTextContent(
        /Lines without a price: 1.*left out of the register totals/,
      );
    });

    it("stays quiet about a line the order already priced", async () => {
      state.valueShown = true;
      const user = userEvent.setup();
      renderPage();
      await user.selectOptions(screen.getByLabelText("From"), "partner-1");
      await screen.findByText("Jasmine Rice");

      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });

    it("stays quiet when the organization tracks no value", async () => {
      const user = userEvent.setup();
      renderPage();
      await user.type(
        screen.getByRole("combobox", { name: "Scan or search a product" }),
        "rice",
      );
      await user.keyboard("{Enter}");
      await screen.findByRole("textbox", {
        name: /How many arrived: Jasmine Rice/,
      });

      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });
  });

  it("fills the sheet from pasted rows", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Paste rows" }));
    await user.click(
      await screen.findByRole("button", { name: "import-stub" }),
    );

    expect(await screen.findByText("Cane Sugar")).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: /How many arrived: Cane Sugar/ }),
    ).toHaveValue("18");
  });

  it("names the pasted rows the catalogue did not match instead of dropping them", async () => {
    state.importResult = {
      imported: 3,
      matched: 1,
      unmatched: 1,
      stubs_created: 0,
      failed: 1,
      errors: [{ row: 4, error: "Quantity must be a number" }],
      no_stock: [],
      lines: [
        {
          id: "pasted-1",
          name: "Cane Sugar",
          quantity: "18",
          product_template_id: "tpl-sugar",
          item_id: null,
          uom_id: "uom-sugar",
          batch_number: null,
          expiry_date: null,
          unit_price: null,
          tax_rate: null,
        },
        {
          id: "pasted-2",
          name: "Ghost thing",
          quantity: "3",
          product_template_id: null,
          item_id: null,
          uom_id: null,
          batch_number: null,
          expiry_date: null,
          unit_price: null,
          tax_rate: null,
        },
      ],
    };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Paste rows" }));
    await user.click(
      await screen.findByRole("button", { name: "import-stub" }),
    );

    // The matched row is on the sheet...
    expect(await screen.findByText("Cane Sugar")).toBeInTheDocument();
    // ...and the row the catalogue refused is named, with its count, rather
    // than silently left out of a receipt the reader would post.
    expect(
      screen.getByText(
        "1 pasted row is not in the catalogue and was not added:",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Ghost thing · 3")).toBeInTheDocument();
    // A row the import could not read at all is named too.
    expect(
      screen.getByText("Row 4: Quantity must be a number"),
    ).toBeInTheDocument();
  });

  it("opens the lot a pasted row brings to a line already on the sheet", async () => {
    state.importResult = {
      imported: 1,
      matched: 1,
      unmatched: 0,
      stubs_created: 0,
      failed: 0,
      errors: [],
      no_stock: [],
      lines: [
        {
          id: "pasted-1",
          name: "Jasmine Rice",
          quantity: "40",
          product_template_id: "tpl-rice",
          item_id: null,
          uom_id: "uom-1",
          batch_number: "L-77",
          expiry_date: null,
          unit_price: null,
          tax_rate: null,
        },
      ],
    };
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");
    await user.click(screen.getByRole("button", { name: "Paste rows" }));
    await user.click(
      await screen.findByRole("button", { name: "import-stub" }),
    );

    expect(await screen.findByLabelText("Lot")).toHaveValue("L-77");
  });

  it("shows each lot a paste brings for one product as a row of its own", async () => {
    state.importResult = {
      imported: 2,
      matched: 2,
      unmatched: 0,
      stubs_created: 0,
      failed: 0,
      errors: [],
      no_stock: [],
      lines: [
        {
          id: "pasted-1",
          name: "Jasmine Rice",
          quantity: "2",
          product_template_id: "tpl-rice",
          item_id: null,
          uom_id: "uom-1",
          batch_number: "LOT-A",
          expiry_date: "2027-01-31",
          unit_price: null,
          tax_rate: null,
        },
        {
          id: "pasted-2",
          name: "Jasmine Rice",
          quantity: "3",
          product_template_id: "tpl-rice",
          item_id: null,
          uom_id: "uom-1",
          batch_number: "LOT-B",
          expiry_date: "2027-02-28",
          unit_price: null,
          tax_rate: null,
        },
      ],
    };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Paste rows" }));
    await user.click(
      await screen.findByRole("button", { name: "import-stub" }),
    );

    const counts = await screen.findAllByRole("textbox", {
      name: /How many arrived: Jasmine Rice/,
    });
    expect(counts.map((input) => (input as HTMLInputElement).value)).toEqual([
      "2",
      "3",
    ]);
    expect(screen.getAllByLabelText("Lot")).toHaveLength(2);
  });

  it("keeps an earlier paste's lot when a later paste brings a third one", async () => {
    const user = userEvent.setup();
    state.importResult = {
      imported: 2,
      matched: 2,
      unmatched: 0,
      stubs_created: 0,
      failed: 0,
      errors: [],
      no_stock: [],
      lines: [
        pastedRow({
          id: "pasted-1",
          quantity: "2",
          batch: "LOT-A",
          expiry: "2027-01-31",
        }),
        pastedRow({
          id: "pasted-2",
          quantity: "3",
          batch: "LOT-B",
          expiry: "2027-02-28",
        }),
      ],
    };
    renderPage();
    await user.click(screen.getByRole("button", { name: "Paste rows" }));
    await user.click(
      await screen.findByRole("button", { name: "import-stub" }),
    );
    await screen.findAllByRole("textbox", {
      name: /How many arrived: Jasmine Rice/,
    });

    // A second paste states another delivery row. The lots already on the
    // sheet are deliveries of their own and must survive it.
    state.importResult = {
      imported: 1,
      matched: 1,
      unmatched: 0,
      stubs_created: 0,
      failed: 0,
      errors: [],
      no_stock: [],
      lines: [
        pastedRow({
          id: "pasted-3",
          quantity: "4",
          batch: "LOT-C",
          expiry: "2027-03-31",
        }),
      ],
    };
    await user.click(screen.getByRole("button", { name: "Paste rows" }));
    await user.click(
      await screen.findByRole("button", { name: "import-stub" }),
    );

    const counts = await screen.findAllByRole("textbox", {
      name: /How many arrived: Jasmine Rice/,
    });
    expect(counts.map((input) => (input as HTMLInputElement).value)).toEqual([
      "2",
      "3",
      "4",
    ]);
    expect(
      screen
        .getAllByLabelText("Lot")
        .map((input) => (input as HTMLInputElement).value),
    ).toEqual(["LOT-A", "LOT-B", "LOT-C"]);
  });

  it("says the order still expects a line the delivery leaves out", async () => {
    ordersHook.mockImplementation(() => ({
      orders: [twoLineOrder()],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    }));
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    // Cane Sugar did not arrive: its row goes, and the order still owes it.
    await user.click(screen.getByRole("button", { name: "Remove Cane Sugar" }));
    // The footer must not call the order complete over a line that is gone.
    expect(
      screen.queryByText("The whole order arrived."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("1 line of the order is still expected."),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
    expect(state.postNew.mock.calls[0][0].data.lines).toHaveLength(1);
    expect(
      await screen.findByText(/PO\/2026\/002 still expects the rest of 1 line/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/PO\/2026\/002 is now received in full/),
    ).not.toBeInTheDocument();
  });

  it("asks for the location the goods go to and puts the reader there", async () => {
    state.locationRequests = serveLocations([
      { id: "loc-1", name: "Main Warehouse" },
      { id: "loc-2", name: "Annex" },
    ]);
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    expect(
      await screen.findByText("Choose the location the goods go to."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("To location")).toHaveFocus();
    // The field itself is marked, as Issue and Move mark theirs, and the
    // mark goes once a location is chosen.
    expect(screen.getByLabelText("To location")).toBeInvalid();
    expect(screen.getByLabelText("From")).toBeValid();
    await user.selectOptions(screen.getByLabelText("To location"), "loc-1");
    expect(screen.getByLabelText("To location")).toBeValid();
    expect(state.postNew).not.toHaveBeenCalled();
  });

  it("asks for a count above zero and puts the reader on the line", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    const quantity = await screen.findByRole("textbox", {
      name: /How many arrived: Jasmine Rice/,
    });
    await user.clear(quantity);
    await user.type(quantity, "0");

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    expect(
      await screen.findByText("Every line needs a quantity above zero."),
    ).toBeInTheDocument();
    await waitFor(() => expect(quantity).toHaveFocus());
    expect(state.postNew).not.toHaveBeenCalled();
  });

  it("adds a scanned product and walks the counts with Enter", async () => {
    const user = userEvent.setup();
    renderPage();
    const scan = screen.getByRole("combobox", {
      name: "Scan or search a product",
    });
    await user.type(scan, "rice");
    await user.keyboard("{Enter}");

    const first = await screen.findByRole("textbox", {
      name: /How many arrived: Jasmine Rice/,
    });
    await waitFor(() => expect(first).toHaveFocus());

    // A second row, so Enter has a next line to move to.
    await user.type(scan, "sugar");
    await user.keyboard("{Enter}");
    await screen.findByText("Cane Sugar");

    first.focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(first).not.toHaveFocus());
  });

  it("scans the barcode typed now, not the hit of the earlier search", async () => {
    // The picker keeps the last list on screen while the next search is in
    // flight, so a slow catalogue leaves the name's hits visible. Enter
    // after a scan replaced that query must not add them: only the answer
    // to what is typed belongs to the press.
    state.search.mockImplementation((query: string, limit?: number) => {
      if (limit === 5) {
        return Promise.resolve([
          {
            product_template_id: "tpl-thinkpad",
            item_id: null,
            name: "ThinkPad T14s Gen 4",
            sku: "TP-1400",
            barcode: "0196881123456",
            uom_id: "uom-tp",
            uom_symbol: "pcs",
          },
        ]);
      }
      if (query.toLowerCase().includes("dell")) {
        return Promise.resolve([
          {
            product_template_id: "tpl-dell",
            item_id: null,
            name: "Dell Latitude 5540",
            sku: "DELL-5540",
            barcode: null,
            uom_id: "uom-dell",
            uom_symbol: "pcs",
          },
        ]);
      }
      // The barcode's own keystroke search is still out.
      return new Promise(() => {});
    });
    renderPage();
    const scan = screen.getByRole("combobox", {
      name: "Scan or search a product",
    });
    const user = userEvent.setup();
    await user.type(scan, "dell");
    await screen.findByText("Dell Latitude 5540");

    // A scan replaces the whole field in one change; the Dell list stays.
    fireEvent.change(scan, { target: { value: "0196881123456" } });
    await act(async () => {
      fireEvent.keyDown(scan, { key: "Enter" });
    });

    expect(
      await screen.findByRole("textbox", {
        name: /How many arrived: ThinkPad T14s Gen 4/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", {
        name: /How many arrived: Dell Latitude 5540/,
      }),
    ).not.toBeInTheDocument();
  });

  it("posts with Ctrl+Enter", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    await user.keyboard("{Control>}{Enter}{/Control}");

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
  });

  it("posts once when the shortcut repeats while the first post is in flight", async () => {
    // The request stays open: the sheet must not wait for its answer before
    // it refuses the next press, or a held key books the delivery twice.
    state.postNew.mockImplementation(() => new Promise(() => {}));
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    await act(async () => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          ctrlKey: true,
          bubbles: true,
        }),
      );
      // The auto-repeat of the same held key, before the post settles.
      window.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          ctrlKey: true,
          repeat: true,
          bubbles: true,
        }),
      );
    });

    expect(state.postNew).toHaveBeenCalledTimes(1);
  });

  it("keeps the press's name until the sheet changes, so a retry is not a second receipt", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");
    const receive = () =>
      screen.getByRole("button", { name: "Receive into stock" });

    // The answer never arrives: the work stays on the sheet and is pressed again.
    state.postNew.mockRejectedValueOnce(new Error("network"));
    await user.click(receive());
    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
    const firstKey = state.postNew.mock.calls[0][0].key;

    // The same sheet is the same press: the server answers with the first receipt.
    state.postNew.mockRejectedValueOnce(new Error("network"));
    await user.click(receive());
    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(2));
    expect(state.postNew.mock.calls[1][0].key).toBe(firstKey);

    // A changed line is another press, with a name of its own.
    const quantity = screen.getByRole("textbox", {
      name: /How many arrived: Jasmine Rice/,
    });
    await user.clear(quantity);
    await user.type(quantity, "39");
    await user.click(receive());
    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(3));
    expect(state.postNew.mock.calls[2][0].key).not.toBe(firstKey);
  });

  it("names the next identical delivery afresh once the receipt is answered", async () => {
    const user = userEvent.setup();
    renderPage();
    const chooseSupplier = () =>
      user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await chooseSupplier();
    await screen.findByText("Jasmine Rice");

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );
    await screen.findByText("PZ/2026/015");
    await user.click(screen.getByRole("button", { name: "Receive more" }));

    // The same delivery handed over a second time: that is another receipt,
    // not a retry of the first press.
    await chooseSupplier();
    await screen.findByText("Jasmine Rice");
    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(2));
    expect(state.postNew.mock.calls[1][0].data).toEqual(
      state.postNew.mock.calls[0][0].data,
    );
    expect(state.postNew.mock.calls[1][0].key).not.toBe(
      state.postNew.mock.calls[0][0].key,
    );
  });

  it("names the delivery after Undo and Receive more afresh too", async () => {
    const user = userEvent.setup();
    renderPage();
    const chooseSupplier = () =>
      user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await chooseSupplier();
    await screen.findByText("Jasmine Rice");

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );
    await screen.findByText("PZ/2026/015");
    await user.click(screen.getByRole("button", { name: "Undo receipt" }));
    expect(await screen.findByText(/COR\/2026\/001/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Receive more" }));
    await chooseSupplier();
    await screen.findByText("Jasmine Rice");
    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(2));
    expect(state.postNew.mock.calls[1][0].key).not.toBe(
      state.postNew.mock.calls[0][0].key,
    );
  });

  it("does not start a draft while a post is in flight", async () => {
    state.postNew.mockImplementation(() => new Promise(() => {}));
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    await act(async () => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          ctrlKey: true,
          bubbles: true,
        }),
      );
    });
    expect(state.postNew).toHaveBeenCalledTimes(1);

    // Both doors make the same receipt out of the same sheet: whichever is
    // running owns the sheet until it answers.
    await user.click(screen.getByRole("button", { name: "Finish later" }));
    expect(state.createDraft).not.toHaveBeenCalled();
  });

  it("does not post while a draft is being saved", async () => {
    state.createDraft.mockImplementation(() => new Promise(() => {}));
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    await user.click(screen.getByRole("button", { name: "Finish later" }));
    expect(state.createDraft).toHaveBeenCalledTimes(1);

    await act(async () => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          ctrlKey: true,
          bubbles: true,
        }),
      );
    });
    expect(state.postNew).not.toHaveBeenCalled();
  });

  it("refuses to post without a supplier", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );
    expect(await screen.findByText("Choose the supplier.")).toBeInTheDocument();
    expect(state.postNew).not.toHaveBeenCalled();
  });
  it("opens on the order a link names, with its lines, and posts it in one press", async () => {
    const user = userEvent.setup();
    renderAt("/warehouse/receive?order=po-1");

    // Nothing chosen by hand: the order brought its supplier and its lines.
    expect(await screen.findByText("Jasmine Rice")).toBeInTheDocument();
    expect(supplierHook).toHaveBeenCalledWith("po-1");
    expect(screen.getByLabelText("From")).toHaveValue("partner-1");
    expect(
      screen.getByText(/PO\/2026\/002 expects 1 line/),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
    expect(state.postNew.mock.calls[0][0].data.lines).toEqual([
      expect.objectContaining({ source_po_line_id: "pol-1" }),
    ]);
    // The way back is to the order, not to a module the reader never asked for.
    await user.click(
      await screen.findByRole("button", { name: "Back to PO/2026/002" }),
    );
    expect(await screen.findByText("Order po-1")).toBeInTheDocument();
  });

  it("lets the reader leave a sheet that is only what the order link loaded", async () => {
    renderAt("/warehouse/receive?order=po-1");
    await screen.findByText("Jasmine Rice");

    // The supplier and the lines came from the order and are still on it:
    // going back loses nothing, so nothing asks.
    expect(useFormGuardStore.getState().dirtyForm).toBeNull();

    // A count the reader changed is their own work, and leaving loses it.
    fireEvent.change(screen.getByLabelText("How many arrived: Jasmine Rice"), {
      target: { value: "38" },
    });
    await waitFor(() =>
      expect(useFormGuardStore.getState().dirtyForm).not.toBeNull(),
    );
  });

  it("asks before leaving once a supplier was chosen by hand", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    expect(useFormGuardStore.getState().dirtyForm).not.toBeNull();
  });

  it("asks before receiving a surplus past the tolerance, then sends the same press", async () => {
    // Past the tolerance a reader who may receive over it is asked, not
    // refused: the server names the surplus and its order line and writes
    // nothing until the same receipt comes back with the answer.
    const question =
      "Jasmine Rice: receiving 44 is 4 more than the 40 left on order PO/2026/002, line 1. Receive the surplus?";
    state.postNew.mockRejectedValueOnce(
      new AxiosError("Conflict", "ERR_BAD_REQUEST", undefined, undefined, {
        status: 409,
        statusText: "Conflict",
        headers: {},
        config: { headers: {} } as never,
        data: {
          detail: { code: "SURPLUS_NEEDS_CONFIRMATION", message: question },
        },
      }),
    );
    const user = userEvent.setup();
    renderAt("/warehouse/receive?order=po-1");
    await screen.findByText("Jasmine Rice");

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(question);
    // A question is not a failure: nothing under the sheet says it failed.
    expect(
      screen.queryByText("Could not receive the delivery."),
    ).not.toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", { name: "Receive the surplus" }),
    );

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(2));
    const [first, second] = state.postNew.mock.calls.map((call) => call[0]);
    expect(first.confirmSurplus).toBe(false);
    expect(second.confirmSurplus).toBe(true);
    // The same press, answered: the server remembers it by its key.
    expect(second.key).toBe(first.key);
    expect(second.data).toEqual(first.data);
    expect(
      await screen.findByText(/PO\/2026\/002 is now received in full/),
    ).toBeInTheDocument();
  });

  it("names the order's open receipt and offers to receive the rest through it", async () => {
    // A short delivery's draft, or a receipt saved for later, speaks for part
    // of what the order owes: received beside it here, the post meets a
    // refusal the sheet does not explain.
    openReceiptsHook.mockImplementation((orderId: string | null) => ({
      receipts:
        orderId === "po-1"
          ? [
              {
                id: "doc-open",
                number: "IN/2026/004",
                type: "IN",
                status: "CONFIRMED",
                created_at: "2026-10-20T08:00:00Z",
              },
            ]
          : [],
      error: null,
      isError: false,
      refetch: vi.fn(),
    }));
    const user = userEvent.setup();
    renderAt("/warehouse/receive?order=po-1");
    await screen.findByText("Jasmine Rice");

    expect(
      screen.getByText(/PO\/2026\/002 already has an open receipt/),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Receive through IN/2026/004" }),
    );

    expect(
      await screen.findByText("Document doc-open#receive"),
    ).toBeInTheDocument();
  });

  it("says it could not look for the order's open receipts rather than that there are none", async () => {
    const refetch = vi.fn();
    openReceiptsHook.mockReturnValue({
      receipts: [],
      error: new Error("network"),
      isError: true,
      refetch,
    });
    const user = userEvent.setup();
    renderAt("/warehouse/receive?order=po-1");
    await screen.findByText("Jasmine Rice");

    expect(
      screen.getByText(
        "Could not check whether this order already has an open receipt.",
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("keeps saying what the order got after the order list moves on", async () => {
    // Posting refreshes the supplier's open orders: the one just received in
    // full is no longer among them. The answer on screen is about the
    // receipt that was posted, so it must not change with that list.
    state.postNew.mockImplementation(async () => {
      ordersHook.mockImplementation(() => ({
        orders: [],
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      }));
      return posted();
    });
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");
    await screen.findByText("Jasmine Rice");

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    expect(
      await screen.findByText(/PO\/2026\/002 is now received in full/),
    ).toBeInTheDocument();
    expect(screen.getByText(/40 pcs\. in total/)).toBeInTheDocument();
  });

  it("asks which product an order line typed by hand is, then posts it", async () => {
    const typed = {
      ...order(),
      lines: [
        {
          ...order().lines[0],
          productTemplateId: null,
          name: "Test laptop Dell",
        },
      ],
    };
    ordersHook.mockImplementation((partnerId: string | null) => ({
      orders: partnerId ? [typed] : [],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    }));
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("From"), "partner-1");

    await user.click(
      await screen.findByRole("button", {
        name: "Which product is “Test laptop Dell”?",
      }),
    );
    await user.click(await screen.findByText("Dell laptop"));
    expect(screen.getByText("Product: Dell laptop")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Receive into stock" }),
    );

    await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
    expect(state.postNew.mock.calls[0][0].data.lines).toEqual([
      expect.objectContaining({
        product_template_id: "tpl-dell",
        source_po_line_id: "pol-1",
      }),
    ]);
  });

  describe("fields another module adds to the sheet", () => {
    const beforeSubmit = vi.fn();

    /** A customer module with a carrier field and a certificate per line. */
    function registerProbe() {
      function CarrierField({
        data,
      }: {
        data: SlotDataMap["document_form_extra"];
      }) {
        return (
          <>
            <p>
              Carrier panel for {data.documentType} from{" "}
              {data.partnerId ?? "nobody"}, {data.lines.length} lines
            </p>
            <button
              type="button"
              onClick={() => data.setMetaData("slot_probe", { carrier: "DHL" })}
            >
              Carrier DHL
            </button>
          </>
        );
      }
      function CertificateField({
        data,
      }: {
        data: SlotDataMap["document_line_form_extra"];
      }) {
        const { registerBeforeSubmit } = data;
        useEffect(
          () => registerBeforeSubmit(() => beforeSubmit(data.line.name)),
          [registerBeforeSubmit, data.line.name],
        );
        return (
          <label>
            Certificate for {data.line.name}
            <input
              value={String(data.line.metaData.slot_probe?.certificate ?? "")}
              onChange={(event) =>
                data.setMetaData("slot_probe", {
                  certificate: event.target.value,
                })
              }
            />
          </label>
        );
      }
      moduleRegistry.register({
        name: "slot-probe",
        routes: [],
        slots: [
          {
            slot: "document_form_extra",
            component: slotComponent(CarrierField),
          },
          {
            slot: "document_line_form_extra",
            component: slotComponent(CertificateField),
          },
        ],
      });
      vi.spyOn(modulesCtx, "useModules").mockReturnValue({
        enabledModules: ["warehouse", "partners", "slot-probe"],
        isModuleEnabled: () => true,
        isLoading: false,
        refreshModules: vi.fn(),
        focusModule: null,
        hiddenModules: [],
      });
    }

    beforeEach(() => {
      beforeSubmit.mockReset();
      registerProbe();
    });

    it("shows the module's panel and a field on every line, told what the sheet holds", async () => {
      const user = userEvent.setup();
      renderPage();
      expect(
        screen.getByText(/Carrier panel for IN from nobody, 0 lines/),
      ).toBeInTheDocument();

      await user.selectOptions(screen.getByLabelText("From"), "partner-1");

      expect(
        await screen.findByText("Certificate for Jasmine Rice"),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Carrier panel for IN from partner-1, 1 lines/),
      ).toBeInTheDocument();
    });

    it("puts a module's line field under the line's lot panel, not above it", async () => {
      // It sat in the product cell between the two link-buttons, above the
      // Lot field, so a certificate "for lot L-100" read as a field of the
      // product rather than of the lot typed below it.
      const user = userEvent.setup();
      renderPage();
      await user.selectOptions(screen.getByLabelText("From"), "partner-1");
      await user.click(
        await screen.findByRole("button", { name: "Lot and expiry" }),
      );

      const lot = screen.getByLabelText("Lot");
      const field = screen.getByLabelText("Certificate for Jasmine Rice");
      expect(
        lot.compareDocumentPosition(field) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });

    it("lets the module save its values before the receipt is sent", async () => {
      const user = userEvent.setup();
      renderPage();
      await user.selectOptions(screen.getByLabelText("From"), "partner-1");
      await screen.findByText("Certificate for Jasmine Rice");

      await user.click(
        screen.getByRole("button", { name: "Receive into stock" }),
      );

      await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
      expect(beforeSubmit).toHaveBeenCalledWith("Jasmine Rice");
      expect(beforeSubmit.mock.invocationCallOrder[0]).toBeLessThan(
        state.postNew.mock.invocationCallOrder[0],
      );
    });

    it("sends what the module put on the document and on the line with the receipt", async () => {
      const user = userEvent.setup();
      renderPage();
      await user.selectOptions(screen.getByLabelText("From"), "partner-1");

      await user.type(
        await screen.findByLabelText("Certificate for Jasmine Rice"),
        "C-1",
      );
      await user.click(screen.getByRole("button", { name: "Carrier DHL" }));
      expect(screen.getByLabelText("Certificate for Jasmine Rice")).toHaveValue(
        "C-1",
      );
      await user.click(
        screen.getByRole("button", { name: "Receive into stock" }),
      );

      await waitFor(() => expect(state.postNew).toHaveBeenCalledTimes(1));
      const sent = state.postNew.mock.calls[0][0].data;
      expect(sent.meta_data).toEqual({ slot_probe: { carrier: "DHL" } });
      expect(sent.lines[0].meta_data).toEqual({
        slot_probe: { certificate: "C-1" },
      });
    });

    it("sends nothing when the module refuses, and says why", async () => {
      beforeSubmit.mockRejectedValue(
        new ReadableError("Enter the certificate for Jasmine Rice"),
      );
      const user = userEvent.setup();
      renderPage();
      await user.selectOptions(screen.getByLabelText("From"), "partner-1");
      await screen.findByText("Certificate for Jasmine Rice");

      await user.click(
        screen.getByRole("button", { name: "Receive into stock" }),
      );

      expect(
        await screen.findByText("Enter the certificate for Jasmine Rice"),
      ).toBeInTheDocument();
      expect(state.postNew).not.toHaveBeenCalled();
    });
  });

  describe("on a phone", () => {
    beforeEach(() => {
      holdAPhone();
      camera.onCode = null;
      state.createDraft.mockResolvedValue({ id: "doc-9", status: "DRAFT" });
      state.confirm
        .mockReset()
        .mockResolvedValue({ id: "doc-9", status: "CONFIRMED" });
    });

    it("puts what the order expects above the question the order has answered", async () => {
      renderAt("/warehouse/receive?order=po-1");

      const note = await screen.findByText("PO/2026/002 expects 1 line.");
      const question = screen.getByText("Where do the goods come from?");
      expect(
        note.compareDocumentPosition(question) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });

    it("hands a To do delivery to the receiving session, not the desk sheet", async () => {
      const user = userEvent.setup();
      renderAt("/warehouse/receive?order=po-1");

      const start = await screen.findByRole("button", {
        name: "Receive one product at a time",
      });
      // The desk sheet's table and its count fields are not on a phone, and
      // the note does not send the reader to lines that are not there.
      expect(
        screen.getByText("PO/2026/002 expects 1 line."),
      ).toBeInTheDocument();
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("textbox", { name: /How many arrived/ }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Receive into stock" }),
      ).not.toBeInTheDocument();

      await user.click(start);

      // The order's lines become a confirmed receipt, and its own page opens
      // the receiving session — the camera, the stepper, the location.
      expect(
        await screen.findByText("Document doc-9#receive"),
      ).toBeInTheDocument();
      expect(state.createDraft).toHaveBeenCalledTimes(1);
      expect(state.createDraft.mock.calls[0][0]).toEqual(
        expect.objectContaining({
          type: "IN",
          partner_id: "partner-1",
          target_location_id: "loc-1",
          lines: [
            expect.objectContaining({
              source_po_line_id: "pol-1",
              expected_quantity: "40",
            }),
          ],
        }),
      );
      expect(state.confirm).toHaveBeenCalledWith("doc-9");
      expect(state.postNew).not.toHaveBeenCalled();
    });

    it("receives a product the order does not list beside the ordered one", async () => {
      // A supplier who still owes an order brings something else on the
      // same truck: the phone takes it in, and the order's lines stay.
      const user = userEvent.setup();
      renderAt("/warehouse/receive?order=po-1");
      await screen.findByRole("button", {
        name: "Receive one product at a time",
      });

      await user.click(screen.getByRole("button", { name: "Scan" }));
      await waitFor(() => expect(camera.onCode).not.toBeNull());
      // The ordered product is counted on the session, not added again.
      await act(async () => {
        camera.onCode?.("rice-code");
      });
      expect(
        await screen.findByText(
          "Jasmine Rice is on the order: count it once receiving starts.",
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("spinbutton", { name: /How many arrived/ }),
      ).not.toBeInTheDocument();

      await act(async () => {
        camera.onCode?.("sugar-code");
      });
      const count = await screen.findByRole("spinbutton", {
        name: "How many arrived: Cane Sugar",
      });
      await user.clear(count);
      await user.type(count, "3");

      await user.click(
        screen.getByRole("button", { name: "Receive one product at a time" }),
      );

      expect(
        await screen.findByText("Document doc-9#receive"),
      ).toBeInTheDocument();
      expect(state.createDraft.mock.calls[0][0]).toEqual(
        expect.objectContaining({
          partner_id: "partner-1",
          lines: [
            expect.objectContaining({
              source_po_line_id: "pol-1",
              expected_quantity: "40",
            }),
            expect.objectContaining({
              product_template_id: "tpl-sugar",
              source_po_line_id: undefined,
              expected_quantity: "3",
            }),
          ],
        }),
      );
      expect(state.confirm).toHaveBeenCalledWith("doc-9");
    });

    it("takes the reader to the draft when the receipt cannot be confirmed", async () => {
      const user = userEvent.setup();
      state.confirm.mockReset().mockRejectedValue(new Error("refused"));
      renderAt("/warehouse/receive?order=po-1");

      await user.click(
        await screen.findByRole("button", {
          name: "Receive one product at a time",
        }),
      );

      // The receipt exists as a draft: a second press would make another.
      expect(await screen.findByText("Document doc-9")).toBeInTheDocument();
    });

    it("counts goods nobody ordered with the camera and hands them to the session", async () => {
      const user = userEvent.setup();
      ordersHook.mockImplementation(() => ({
        orders: [],
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      }));
      renderAt("/warehouse/receive");

      await user.selectOptions(screen.getByLabelText("From"), "partner-1");

      // No order lists the delivery, and still no desk sheet on a phone.
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Receive into stock" }),
      ).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Scan" }));
      // The camera is its own chunk, there once the button asked for it.
      await waitFor(() => expect(camera.onCode).not.toBeNull());
      await act(async () => {
        camera.onCode?.("sugar-code");
      });

      const count = await screen.findByRole("spinbutton", {
        name: "How many arrived: Cane Sugar",
      });
      expect(count).toHaveValue(1);
      // The stepper's buttons step by the unit, which this test does not
      // load; the number typed between them is the same count.
      expect(
        screen.getByRole("button", { name: "Increase" }),
      ).toBeInTheDocument();
      await user.clear(count);
      await user.type(count, "3");

      await user.click(
        screen.getByRole("button", { name: "Receive one product at a time" }),
      );

      // The counted goods become a confirmed receipt, and its session puts
      // each one away at its suggested location.
      expect(
        await screen.findByText("Document doc-9#receive"),
      ).toBeInTheDocument();
      expect(state.createDraft.mock.calls[0][0]).toEqual(
        expect.objectContaining({
          type: "IN",
          partner_id: "partner-1",
          lines: [
            expect.objectContaining({
              product_template_id: "tpl-sugar",
              expected_quantity: "3",
            }),
          ],
        }),
      );
      expect(state.confirm).toHaveBeenCalledWith("doc-9");
    });

    it("names a camera code the catalogue does not know", async () => {
      const user = userEvent.setup();
      ordersHook.mockImplementation(() => ({
        orders: [],
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      }));
      state.search.mockResolvedValue([]);
      renderAt("/warehouse/receive");

      await user.click(screen.getByRole("button", { name: "Scan" }));
      await waitFor(() => expect(camera.onCode).not.toBeNull());
      await act(async () => {
        camera.onCode?.("0000");
      });

      expect(
        await screen.findByText("No product found for “0000”."),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("spinbutton", { name: /How many arrived/ }),
      ).not.toBeInTheDocument();
    });
  });
});

describe("ReceiveGoodsPage — an account that cannot post", () => {
  beforeEach(() => {
    rights.write = false;
  });

  it("is told once and is offered no pickers or Post", () => {
    renderPage();

    expect(screen.getByRole("note")).toBeInTheDocument();
    expect(screen.queryByLabelText("From")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add to stock" }),
    ).not.toBeInTheDocument();
  });
});
