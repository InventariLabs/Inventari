import { act, createElement } from "react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@/test/utils";
import DocumentFormModal from "./DocumentFormModal";
import * as modulesCtx from "@/contexts/ModulesContext";
import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";
import type { SlotDataMap } from "@/lib/moduleRegistry";
import type { ComponentProps } from "react";
import type * as RealEditorModule from "@/modules/warehouse/components/DocumentLinesEditor";
import * as documentHooks from "@/modules/warehouse/hooks/useDocuments";
import * as partnerHooks from "@/modules/partners/hooks/usePartners";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";
import { rememberLastUsedLocations } from "@/modules/warehouse/lib/lastUsedLocations";
import * as itemHooks from "@/modules/inventory/hooks/useItems";
import * as profileHooks from "@/modules/warehouse/hooks/useDocumentProfile";
import * as productSearchHooks from "@/modules/warehouse/hooks/useProductSearch";

// The price-hint rework is modal logic; one test swaps the line editor
// for a stand-in that reports hint results on cue. Disabled by default,
// so every other test in this file renders the real editor.
const editorStub = vi.hoisted(() => ({
  enabled: false,
  reportHint: undefined as
    ((lineKey: string, suggested: boolean) => void) | undefined,
  lineKeys: [] as string[],
}));

vi.mock(
  "@/modules/warehouse/components/DocumentLinesEditor",
  async (importOriginal) => {
    const actual =
      await importOriginal<
        typeof import("@/modules/warehouse/components/DocumentLinesEditor")
      >();
    return {
      DocumentLinesEditor: (
        props: ComponentProps<typeof RealEditorModule.DocumentLinesEditor>,
      ) => {
        if (!editorStub.enabled) {
          return createElement(actual.DocumentLinesEditor, props);
        }
        editorStub.reportHint = props.onPriceHintResult as
          ((lineKey: string, suggested: boolean) => void) | undefined;
        const lines: Array<{ _key: string }> = props.lines ?? [];
        editorStub.lineKeys = lines.map((line) => line._key);
        const indexOfKey = (key: string) =>
          lines.findIndex((line) => line._key === key);
        return createElement(
          "div",
          null,
          lines.map((line) =>
            createElement(
              "div",
              { key: line._key },
              createElement(
                "div",
                { "data-testid": `extra ${line._key}` },
                props.renderLineExtra?.(line),
              ),
              createElement(
                "button",
                {
                  type: "button",
                  onClick: () => editorStub.reportHint?.(line._key, false),
                },
                `simulate hint miss for ${line._key}`,
              ),
              createElement(
                "button",
                {
                  type: "button",
                  onClick: () =>
                    (
                      props.onUpdateLine as (
                        index: number,
                        updates: Record<string, unknown>,
                      ) => void
                    )(indexOfKey(line._key), { unit_price: "4.50" }),
                },
                `price line ${line._key}`,
              ),
            ),
          ),
          createElement(
            "button",
            { type: "button", onClick: props.onAddEmptyLine as () => void },
            "Add line",
          ),
        );
      },
    };
  },
);

// The import sheet has its own spec; here it stands in for "an import read
// these lines", reporting what the form handed it.
const importStub = vi.hoisted(() => ({
  lines: [] as Array<Record<string, unknown>>,
}));

vi.mock("@/modules/warehouse/components/DocumentImportModal", () => ({
  DocumentImportModal: (props: {
    documentType?: string;
    sourceLocationId?: string;
    onImported?: (result: { lines: unknown[] }) => void;
  }) =>
    createElement(
      "button",
      {
        type: "button",
        onClick: () => props.onImported?.({ lines: importStub.lines }),
      },
      `finish import of ${props.documentType} from ${props.sourceLocationId}`,
    ),
}));

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
  Toaster: () => null,
}));

vi.mock("@/lib/api", () => ({
  labelsApi: { scan: vi.fn() },
}));

vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: vi.fn(() => ({
    isCameraActive: false,
    scannerError: null,
    isTorchOn: false,
    toggleTorch: vi.fn(),
    restartCamera: vi.fn(),
  })),
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  useCreateDocument: vi.fn(),
  useUpdateDocument: vi.fn(),
  // The form re-reads the document after a line import writes to it.
  useFetchDocument: () => vi.fn(),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: vi.fn(),
}));

vi.mock("@/modules/partners/hooks/usePartners", () => ({
  usePartners: vi.fn(),
  usePartner: vi.fn(() => ({ data: undefined, isError: false })),
}));

/** The organization's places, as the server holds them. */
const PLACES = [
  { id: "loc-1", name: "Receiving" },
  { id: "loc-2", name: "Main Shelf" },
];
let locationRequests: URLSearchParams[] = [];

/** The pickers search the places on the server: wait until they have answered. */
async function placesLoaded() {
  await waitFor(() =>
    expect(
      screen.getAllByRole("option", { name: "Main Shelf" }).length,
    ).toBeGreaterThan(0),
  );
}

vi.mock("@/modules/inventory/hooks/useItems", () => ({
  useItems: vi.fn(),
}));

vi.mock("@/modules/warehouse/hooks/useProductSearch", () => ({
  useProductSearch: vi.fn(),
}));

vi.mock("@/modules/partners/components/PartnerInlineCreate", () => ({
  PartnerInlineCreate: ({
    initialName,
    onCreated,
  }: {
    initialName: string;
    onCreated: (partner: { id: string; type: string }) => void;
  }) => (
    <div data-testid="partner-inline-create">
      <span data-testid="partner-inline-name">{initialName}</span>
      {/* A supplier, whatever field opened the layer — the trap the real
          layer's default type set up on every dispatch. */}
      <button
        type="button"
        onClick={() => onCreated({ id: "new-partner-99", type: "SUPPLIER" })}
      >
        Simulate Create
      </button>
    </div>
  ),
}));

// Mock SearchableCombobox as a native <select> for predictable test interactions
vi.mock("@/components/ui/SearchableCombobox", () => ({
  SearchableCombobox: ({
    options,
    value,
    onChange,
    placeholder,
    createLabel,
    onCreateNew,
    error,
    id,
    title,
    emptyMessage,
  }: {
    options: { id: string; name: string }[];
    value: string;
    onChange: (v: string) => void;
    placeholder?: string;
    createLabel?: string;
    onCreateNew?: (query: string) => void;
    error?: string;
    id?: string;
    title?: string;
    emptyMessage?: React.ReactNode;
  }) => (
    // Mirrors the real control's error contract: aria-invalid on the field,
    // an id'd role="alert" message, and aria-describedby joining them.
    <div>
      <select
        id={id}
        aria-label={placeholder ?? title ?? "searchable-combobox"}
        aria-invalid={error ? true : undefined}
        aria-describedby={error && id ? `${id}-error` : undefined}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{placeholder}</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
      {options.length === 0 && emptyMessage && <p>{emptyMessage}</p>}
      {onCreateNew && createLabel && (
        <button type="button" onClick={() => onCreateNew("test-query")}>
          {createLabel}
        </button>
      )}
      {error && (
        <p id={id ? `${id}-error` : undefined} role="alert">
          {error}
        </p>
      )}
    </div>
  ),
}));

describe("DocumentFormModal", () => {
  const createMutate = vi.fn();
  const updateMutate = vi.fn();

  // A receipt line names a product on the list: the search offers one, and
  // the line takes it.
  function offerWidget() {
    vi.mocked(productSearchHooks.useProductSearch).mockReturnValue({
      results: [
        {
          product_template_id: "pt-widget",
          name: "Widget",
          brand: null,
          barcode: null,
          sku: null,
          image_url: null,
          uom_id: null,
        },
      ],
      isLoading: false,
      error: null,
      search: vi.fn(),
      selectResult: vi.fn(),
      clearSearch: vi.fn(),
      query: "",
      setQuery: vi.fn(),
    } as unknown as ReturnType<typeof productSearchHooks.useProductSearch>);
  }

  async function pickWidget(
    user: ReturnType<typeof userEvent.setup>,
    input: HTMLElement,
  ) {
    await user.type(input, "Widget");
    await user.click(await screen.findByRole("option", { name: /Widget/ }));
  }

  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(productSearchHooks.useProductSearch).mockReturnValue({
      results: [],
      isLoading: false,
      error: null,
      search: vi.fn(),
      selectResult: vi.fn(),
      clearSearch: vi.fn(),
      query: "",
      setQuery: vi.fn(),
    } as unknown as ReturnType<typeof productSearchHooks.useProductSearch>);

    vi.mocked(documentHooks.useCreateDocument).mockReturnValue({
      mutate: createMutate,
      isPending: false,
    } as unknown as ReturnType<typeof documentHooks.useCreateDocument>);
    vi.mocked(documentHooks.useUpdateDocument).mockReturnValue({
      mutate: updateMutate,
      isPending: false,
    } as unknown as ReturnType<typeof documentHooks.useUpdateDocument>);
    vi.mocked(partnerHooks.usePartners).mockReturnValue({
      data: {
        items: [
          {
            id: "partner-1",
            name: "ACME Supplies",
          },
        ],
        total: 1,
      },
    } as unknown as ReturnType<typeof partnerHooks.usePartners>);
    locationRequests = serveLocations(PLACES);
    vi.mocked(itemHooks.useItems).mockReturnValue({
      data: {
        items: [],
        total: 0,
        limit: 15,
        offset: 0,
        has_more: false,
      },
    } as unknown as ReturnType<typeof itemHooks.useItems>);
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: {
        id: "profile-1",
        organization_id: "org-1",
        name: "Simple",
        value_tracking_enabled: false,
        tax_handling: "NONE",
        default_tax_rate: null,
        require_partner_tax_id: false,
        numbering_format: "{TYPE}/{YEAR}/{SEQ:03d}",
        type_labels: null,
        default_unit: "pcs",
        visible_line_fields: [],
        print_template: "standard",
        default_currency: null,
        created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:00",
      },
      isLoading: false,
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
  });

  it("uses a wider desktop shell for document editing", async () => {
    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    // The Sheet panel carries the width. The shell inside it must not repeat
    // the height cap — two nested 90vh boxes made the form scroll on content
    // that fits, the parent's border having already spent 2px of the cap.
    expect(screen.getByRole("dialog")).toHaveClass(
      "sm:max-w-4xl",
      "xl:max-w-6xl",
      "3xl:max-w-7xl",
    );
    expect(
      screen.getByTestId("document-form-modal-shell").className,
    ).not.toContain("max-h-");
  });

  it("shows desktop line headers once the user adds a line", async () => {
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add line" }));
    });

    expect(
      screen.getByTestId("document-lines-desktop-header"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("document-lines-table-shell"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Quantity").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Unit").length).toBeGreaterThan(0);
  });

  it("shows correct fields for transfer document type", async () => {
    await act(async () => {
      render(<DocumentFormModal initialType="INT" onClose={vi.fn()} />);
    });

    await waitFor(() => {
      expect(
        screen.getByLabelText("Choose where the goods come from"),
      ).toBeInTheDocument();
      expect(
        screen.getByLabelText("Choose where the goods go"),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText("Select partner")).not.toBeInTheDocument();
    });
  });

  it("does not blame the module policy when it hides nothing the picker offers", async () => {
    // The virtual counterparts and an archived shelf: rows no policy
    // reveals, so the switch the old message named would change nothing.
    serveLocations([
      { id: "loc-consumed", name: "Consumed", usage: "customer" },
      { id: "loc-old", name: "Old Shelf", settings: { archived: true } },
    ]);

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    expect(
      await screen.findByText(/no location here that can hold stock/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/belongs to a module/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Open settings" }),
    ).not.toBeInTheDocument();
  });

  it("names the submit button after the organization's own name for the type", async () => {
    const current = vi.mocked(profileHooks.useDocumentProfile)();
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      ...current,
      data: { ...current.data, type_labels: { IN: "TESTNAME" } },
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    expect(
      screen.getByRole("button", { name: "Create Receipt (TESTNAME)" }),
    ).toBeInTheDocument();
  });

  it("keeps the type's name beside a bare preset code on the submit button", async () => {
    const current = vi.mocked(profileHooks.useDocumentProfile)();
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      ...current,
      data: { ...current.data, type_labels: { OUT: "WA" } },
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);

    await act(async () => {
      render(<DocumentFormModal initialType="OUT" onClose={vi.fn()} />);
    });

    expect(
      screen.getByRole("button", { name: "Create Delivery (WA)" }),
    ).toBeInTheDocument();
  });

  it("tells the reader there is nowhere to put stock when the organization has no locations", async () => {
    serveLocations([]);

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    expect(
      await screen.findByText(/no location here that can hold stock/i),
    ).toBeInTheDocument();
  });

  it.each([
    ["IN", "Create receipt"],
    ["OUT", "Create dispatch"],
    ["SCRAP", "Create scrap"],
    ["CORRECTION", "Create correction"],
  ])(
    "names the submit button after what the type does (%s)",
    async (type, label) => {
      await act(async () => {
        render(
          <DocumentFormModal
            initialType={type as "SCRAP" | "CORRECTION" | "IN" | "OUT"}
            onClose={vi.fn()}
          />,
        );
      });

      expect(
        screen.getByRole("button", { name: label as string }),
      ).toBeInTheDocument();
    },
  );

  it("submits a receipt payload with selected partner, target, and line", async () => {
    const user = userEvent.setup();
    offerWidget();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    const [partnerSelect, targetSelect] = screen.getAllByRole("combobox");

    await placesLoaded();
    await act(async () => {
      await user.selectOptions(partnerSelect, "partner-1");
      await user.selectOptions(targetSelect, "loc-2");
    });

    const lineNameInputs = screen.getAllByPlaceholderText("Item");
    const lineNameInput = lineNameInputs[0];

    await act(async () => {
      await pickWidget(user, lineNameInput);
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Create receipt" }));
    });

    await waitFor(() => {
      expect(createMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "IN",
          partner_id: "partner-1",
          target_location_id: "loc-2",
          lines: [
            expect.objectContaining({
              product_template_id: "pt-widget",
              name: "Widget",
              expected_quantity: 1,
            }),
          ],
        }),
        expect.any(Object),
      );
    });
  });

  // "Test laptop Dell" at 3000 was typed into a receipt and posted into
  // stock that no product stood behind. A typed name is now picked from the
  // list or made a product first; the receipt is not saved with it as words.
  it("does not save a receipt line typed by hand", async () => {
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    const [partnerSelect, targetSelect] = screen.getAllByRole("combobox");
    await placesLoaded();
    await act(async () => {
      await user.selectOptions(partnerSelect, "partner-1");
      await user.selectOptions(targetSelect, "loc-2");
      await user.type(screen.getAllByPlaceholderText("Item")[0], "Widget");
      await user.click(screen.getByRole("button", { name: "Create receipt" }));
    });

    expect(createMutate).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith(
      "Pick a product from the list, or add this name as a new product",
    );
  });

  it("adds an existing item from search results into lines", async () => {
    const user = userEvent.setup();

    const mockSelectResult = vi.fn((_product: Record<string, unknown>) => {
      vi.mocked(productSearchHooks.useProductSearch).mockReturnValue({
        results: [],
        isLoading: false,
        error: null,
        search: vi.fn(),
        selectResult: mockSelectResult,
        clearSearch: vi.fn(),
        query: "",
        setQuery: vi.fn(),
      } as unknown as ReturnType<typeof productSearchHooks.useProductSearch>);
    });

    vi.mocked(productSearchHooks.useProductSearch).mockReturnValue({
      results: [
        {
          product_template_id: "pt-1",
          name: "Existing Widget",
          brand: "ACME",
          barcode: "123456",
          sku: null,
          image_url: null,
          uom_id: null,
        },
      ],
      isLoading: false,
      error: null,
      search: vi.fn(),
      selectResult: mockSelectResult,
      clearSearch: vi.fn(),
      query: "",
      setQuery: vi.fn(),
    } as unknown as ReturnType<typeof productSearchHooks.useProductSearch>);

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    const lineNameInput = screen.getAllByPlaceholderText("Item")[0];

    await act(async () => {
      await user.type(lineNameInput, "Wid");
    });

    await waitFor(() => {
      expect(screen.getByText("Existing Widget")).toBeInTheDocument();
    });

    await act(async () => {
      await user.click(screen.getByText("Existing Widget"));
    });
  });

  it("opens inline quick add from empty search results and appends a new line", async () => {
    const user = userEvent.setup();

    let searchCalls = 0;
    const mockSearch = vi.fn(() => {
      searchCalls++;
    });

    vi.mocked(productSearchHooks.useProductSearch).mockReturnValue({
      results: [],
      isLoading: false,
      error: null,
      search: mockSearch,
      selectResult: vi.fn(),
      clearSearch: vi.fn(),
      query: "",
      setQuery: vi.fn(),
    } as unknown as ReturnType<typeof productSearchHooks.useProductSearch>);

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    const lineNameInput = screen.getAllByPlaceholderText("Item")[0];

    await act(async () => {
      await user.type(lineNameInput, "Novel");
    });

    expect(mockSearch).toHaveBeenCalled();
  });

  it("triggers product search when typing in line name input", async () => {
    const user = userEvent.setup();

    const mockSearch = vi.fn();

    vi.mocked(productSearchHooks.useProductSearch).mockReturnValue({
      results: [],
      isLoading: false,
      error: null,
      search: mockSearch,
      selectResult: vi.fn(),
      clearSearch: vi.fn(),
      query: "",
      setQuery: vi.fn(),
    } as unknown as ReturnType<typeof productSearchHooks.useProductSearch>);

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    const lineNameInput = screen.getAllByPlaceholderText("Item")[0];

    await act(async () => {
      await user.type(lineNameInput, "No");
    });

    expect(mockSearch).toHaveBeenCalledWith("No");
  });

  it("shows all inline field errors at once on submit (aggregate validation, full list)", async () => {
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    // Default line has empty name and no item_id. Submit without touching
    // anything: partner + target + line-name should all be reported at once.
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Create receipt" }));
    });

    expect(
      screen.getByText("Partner is required for this document type"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("To location is required for this document type"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Each manual line requires an item name"),
    ).toBeInTheDocument();
    expect(createMutate).not.toHaveBeenCalled();
  });

  it("clears individual field errors when the user fixes each one (live update)", async () => {
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Create receipt" }));
    });

    // All three errors present.
    expect(
      screen.getByText("Partner is required for this document type"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("To location is required for this document type"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Each manual line requires an item name"),
    ).toBeInTheDocument();

    // Fix the partner: partner error disappears, target + line-name remain.
    const [partnerSelect, targetSelect] = screen.getAllByRole("combobox");
    await act(async () => {
      await user.selectOptions(partnerSelect, "partner-1");
    });
    await waitFor(() => {
      expect(
        screen.queryByText("Partner is required for this document type"),
      ).not.toBeInTheDocument();
    });
    expect(
      screen.getByText("To location is required for this document type"),
    ).toBeInTheDocument();

    // Fix the target: target error disappears, line-name error remains.
    await placesLoaded();
    await act(async () => {
      await user.selectOptions(targetSelect, "loc-2");
    });
    await waitFor(() => {
      expect(
        screen.queryByText("To location is required for this document type"),
      ).not.toBeInTheDocument();
    });
    expect(
      screen.getByText("Each manual line requires an item name"),
    ).toBeInTheDocument();

    // Type a name in the line: line-name error disappears. No submit.
    const lineNameInput = screen.getAllByPlaceholderText("Item")[0];
    await act(async () => {
      await user.type(lineNameInput, "Widget");
    });
    await waitFor(() => {
      expect(
        screen.queryByText("Each manual line requires an item name"),
      ).not.toBeInTheDocument();
    });
    expect(createMutate).not.toHaveBeenCalled();
  });

  it("surfaces 422 line errors inline (422 → fields)", async () => {
    const user = userEvent.setup();

    // Simulate the backend rejecting the create with a 422 array detail
    // (FastAPI / Pydantic shape: { detail: [{ loc, msg, type }] }).
    // We use a plain Error stamped with isAxiosError + response so axios's
    // isAxiosError() check (which reads `error.isAxiosError === true`)
    // recognizes it regardless of AxiosError class identity across module
    // resolution paths in tests.
    const fakeAxiosError = Object.assign(
      new Error("Request failed with status code 422"),
      {
        isAxiosError: true,
        response: {
          status: 422,
          data: {
            detail: [
              {
                loc: ["body", "partner_id"],
                msg: "Partner id is required",
                type: "value_error",
              },
            ],
          },
        },
      },
    );
    createMutate.mockImplementationOnce((_data, options) => {
      options?.onError?.(fakeAxiosError);
    });
    offerWidget();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    // Fill client-required fields so the form passes the client validator
    // and reaches the create mutation.
    const [partnerSelect, targetSelect] = screen.getAllByRole("combobox");
    const lineNameInput = screen.getAllByPlaceholderText("Item")[0];
    await placesLoaded();
    await act(async () => {
      await pickWidget(user, lineNameInput);
      await user.selectOptions(partnerSelect, "partner-1");
      await user.selectOptions(targetSelect, "loc-2");
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Create receipt" }));
    });

    // End-to-end smoke: the create mutation was invoked, the 422 response
    // was routed through the modal's error handler, and the toast surfaced
    // the server's array-detail message (not the generic fallback). The
    // per-field mapping is covered by parseApiValidationErrors unit tests
    // and the aggregate validation tests.
    expect(createMutate).toHaveBeenCalled();
    // The 422 field is named now — the message no longer arrives alone.
    expect(toastError).toHaveBeenCalledWith(
      "partner_id: Partner id is required",
    );
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("does not submit OUT document without required partner and source location", async () => {
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="OUT" onClose={vi.fn()} />);
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add line" }));
    });

    const lineNameInputs = screen.getAllByPlaceholderText("Item");
    const lineNameInput = lineNameInputs[lineNameInputs.length - 1];

    await act(async () => {
      await user.type(lineNameInput, "Widget");
      await user.click(screen.getByRole("button", { name: "Create dispatch" }));
    });

    expect(createMutate).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalled();
  });

  it("scopes the line search to the source location on a dispatch", async () => {
    // A dispatch line has to name an item, and only the stock in the source
    // location has one — the catalogue search offered templates the form then
    // refused, quoting a rule the reader had no way to satisfy.
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="OUT" onClose={vi.fn()} />);
    });

    const [, sourceSelect] = screen.getAllByRole("combobox");
    await placesLoaded();
    await act(async () => {
      await user.selectOptions(sourceSelect, "loc-1");
    });

    expect(productSearchHooks.useProductSearch).toHaveBeenCalledWith(
      expect.objectContaining({ locationId: "loc-1" }),
    );
  });

  it("tells a dispatch's line search which location it is limited to", async () => {
    // Searching for stock that stands elsewhere answered "not found" and
    // nothing more; the list now says what it covers.
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="OUT" onClose={vi.fn()} />);
    });

    const [, sourceSelect] = screen.getAllByRole("combobox");
    await placesLoaded();
    await act(async () => {
      await user.selectOptions(sourceSelect, "loc-1");
    });
    await act(async () => {
      await user.type(screen.getAllByPlaceholderText("Item")[0], "Gouda");
    });

    expect(screen.getByText("Products in Receiving")).toBeInTheDocument();
  });

  it("keeps the line search on the catalogue for a receipt", async () => {
    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    expect(productSearchHooks.useProductSearch).toHaveBeenCalledWith(
      expect.objectContaining({ locationId: undefined }),
    );
  });

  it("submits a dispatch line chosen from the stock search", async () => {
    const user = userEvent.setup();

    vi.mocked(productSearchHooks.useProductSearch).mockReturnValue({
      results: [
        {
          product_template_id: null,
          item_id: "item-9",
          available_quantity: 7,
          uom_symbol: "pcs",
          name: "Bolt M8 crate",
          brand: null,
          barcode: null,
          sku: null,
          image_url: null,
          uom_id: null,
        },
      ],
      isLoading: false,
      error: null,
      search: vi.fn(),
      selectResult: vi.fn(),
      clearSearch: vi.fn(),
      query: "",
      setQuery: vi.fn(),
    } as unknown as ReturnType<typeof productSearchHooks.useProductSearch>);

    await act(async () => {
      render(<DocumentFormModal initialType="OUT" onClose={vi.fn()} />);
    });

    const [partnerSelect, sourceSelect] = screen.getAllByRole("combobox");
    await placesLoaded();
    await act(async () => {
      await user.selectOptions(partnerSelect, "partner-1");
      await user.selectOptions(sourceSelect, "loc-1");
    });

    const lineNameInput = screen.getAllByPlaceholderText("Item")[0];
    await act(async () => {
      await user.type(lineNameInput, "Bol");
    });
    await waitFor(() => {
      expect(screen.getByText("Bolt M8 crate")).toBeInTheDocument();
    });
    await act(async () => {
      await user.click(screen.getByText("Bolt M8 crate"));
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Create dispatch" }));
    });

    await waitFor(() => {
      expect(createMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "OUT",
          source_location_id: "loc-1",
          lines: [expect.objectContaining({ item_id: "item-9" })],
        }),
        expect.any(Object),
      );
    });
  });

  it("offers the line import while a dispatch is still being written", async () => {
    // Import lived behind "save the draft, then edit" — and a draft cannot
    // be saved without a line, so an order arriving as a spreadsheet was
    // typed in by hand.
    const user = userEvent.setup();
    importStub.lines = [
      {
        id: "read-1",
        name: "Jogurt naturalny 400 g",
        quantity: "8",
        item_id: "record-1",
        product_template_id: "tpl-1",
      },
    ];

    await act(async () => {
      render(<DocumentFormModal initialType="OUT" onClose={vi.fn()} />);
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Import lines" }));
    });
    expect(toastError).toHaveBeenCalledWith(
      expect.stringMatching(/source location first/),
    );
    expect(screen.queryByRole("button", { name: /finish import/ })).toBeNull();

    const [partnerSelect, sourceSelect] = screen.getAllByRole("combobox");
    await placesLoaded();
    await act(async () => {
      await user.selectOptions(partnerSelect, "partner-1");
      await user.selectOptions(sourceSelect, "loc-1");
      await user.click(screen.getByRole("button", { name: "Import lines" }));
    });
    await act(async () => {
      await user.click(
        screen.getByRole("button", { name: "finish import of OUT from loc-1" }),
      );
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Create dispatch" }));
    });

    // The blank line the form opened with gave way to the imported one.
    await waitFor(() => {
      expect(createMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          lines: [
            expect.objectContaining({
              item_id: "record-1",
              product_template_id: "tpl-1",
              expected_quantity: 8,
            }),
          ],
        }),
        expect.any(Object),
      );
    });
  });

  it("does not submit INT document without required source and target locations", async () => {
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="INT" onClose={vi.fn()} />);
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add line" }));
    });

    const lineNameInputs = screen.getAllByPlaceholderText("Item");
    const lineNameInput = lineNameInputs[lineNameInputs.length - 1];

    await act(async () => {
      await user.type(lineNameInput, "Widget");
      await user.click(screen.getByRole("button", { name: "Create transfer" }));
    });

    expect(createMutate).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalled();
  });

  it("hides optional line fields until the user expands them", async () => {
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add line" }));
    });

    expect(screen.queryByLabelText("Batch number")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Expiry date")).not.toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getAllByTitle("More fields")[0]);
    });

    expect(screen.getByLabelText("Batch number")).toBeInTheDocument();
    expect(screen.queryByLabelText("Expiry date")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add expiry date" }),
    ).toBeInTheDocument();
  });

  it("includes line notes in the create payload after expanding more fields", async () => {
    const user = userEvent.setup();
    offerWidget();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    await placesLoaded();
    await act(async () => {
      const [partnerSelect, targetSelect] = screen.getAllByRole("combobox");
      await user.selectOptions(partnerSelect, "partner-1");
      await user.selectOptions(targetSelect, "loc-2");
    });

    const lineNameInputs = screen.getAllByPlaceholderText("Item");
    const lineNameInput = lineNameInputs[0];

    await act(async () => {
      await pickWidget(user, lineNameInput);
      await user.click(screen.getAllByTitle("More fields")[0]);
    });

    // The document header carries a "Notes" field of its own, so target the
    // line's field by id rather than by accessible name.
    const lineNotesInput = await screen.findByLabelText("Notes", {
      selector: "#line-item-0-notes",
    });

    await act(async () => {
      await user.type(lineNotesInput, "Handle with care");
      await user.click(screen.getByRole("button", { name: "Create receipt" }));
    });

    await waitFor(() => {
      expect(createMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          lines: [
            expect.objectContaining({
              name: "Widget",
              notes: "Handle with care",
            }),
          ],
        }),
        expect.any(Object),
      );
    });
  });

  it("uses a type-aware create CTA for delivery and transfer documents", async () => {
    await act(async () => {
      render(<DocumentFormModal initialType="OUT" onClose={vi.fn()} />);
    });

    expect(
      screen.getByRole("button", { name: "Create dispatch" }),
    ).toBeInTheDocument();

    await act(async () => {
      render(<DocumentFormModal initialType="INT" onClose={vi.fn()} />);
    });

    expect(
      screen.getByRole("button", { name: "Create transfer" }),
    ).toBeInTheDocument();
  });

  it("opens inline partner create when create button clicked and auto-selects partner", async () => {
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    const createBtn = screen.getByText("+ Create new partner");
    await act(async () => {
      await user.click(createBtn);
    });

    expect(screen.getByTestId("partner-inline-create")).toBeInTheDocument();
    expect(screen.getByTestId("partner-inline-name")).toHaveTextContent(
      "test-query",
    );

    await act(async () => {
      await user.click(screen.getByText("Simulate Create"));
    });

    await waitFor(() => {
      expect(
        screen.queryByTestId("partner-inline-create"),
      ).not.toBeInTheDocument();
    });
  });

  // A dispatch's recipient picker lists customers only. The inline layer
  // used to start on "Supplier" regardless of the field that opened it, and
  // the created partner went straight into the field's value: the picker
  // (filtered to the role set) showed the placeholder, the form treated the
  // field as filled, and the submit never mentioned it.
  it("refuses a supplier as the dispatch recipient and reports the empty field", async () => {
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="OUT" onClose={vi.fn()} />);
    });

    await act(async () => {
      await user.click(screen.getByText("+ Create new partner"));
    });
    await act(async () => {
      await user.click(screen.getByText("Simulate Create"));
    });

    // The layer stays open — the type select inside it is the recovery.
    expect(screen.getByTestId("partner-inline-create")).toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Create dispatch" }));
    });
    expect(
      screen.getByText("Partner is required for this document type"),
    ).toBeInTheDocument();
  });

  // Esc must close the inline partner-create popover first, not
  // discard the whole document form.
  it("closes the inline partner-create on Esc without closing the modal", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={onClose} />);
    });

    await act(async () => {
      await user.click(screen.getByText("+ Create new partner"));
    });
    expect(screen.getByTestId("partner-inline-create")).toBeInTheDocument();

    await act(async () => {
      await user.keyboard("{Escape}");
    });

    // Popover dismissed…
    await waitFor(() => {
      expect(
        screen.queryByTestId("partner-inline-create"),
      ).not.toBeInTheDocument();
    });
    // …but the modal was NOT closed (form state preserved).
    expect(onClose).not.toHaveBeenCalled();
  });
  it("hands the created document to the caller instead of just closing", async () => {
    // Saving dropped the user back on the list with a toast; the next step is
    // almost always to confirm the document or add lines to it, and nothing
    // took them there.
    const onClose = vi.fn();
    const onCreated = vi.fn();
    const created = { id: "doc-new-1", number: "IN/2026/010" };
    const user = userEvent.setup();
    createMutate.mockImplementationOnce(
      (_payload: unknown, opts?: { onSuccess?: (doc: unknown) => void }) =>
        opts?.onSuccess?.(created),
    );
    offerWidget();

    await act(async () => {
      render(
        <DocumentFormModal
          initialType="IN"
          onClose={onClose}
          onCreated={onCreated}
        />,
      );
    });

    const [partnerSelect, targetSelect] = screen.getAllByRole("combobox");
    const lineNameInput = screen.getAllByPlaceholderText("Item")[0];
    await placesLoaded();
    await act(async () => {
      await pickWidget(user, lineNameInput);
      await user.selectOptions(partnerSelect, "partner-1");
      await user.selectOptions(targetSelect, "loc-2");
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Create receipt" }));
    });

    expect(onCreated).toHaveBeenCalledWith(created);
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("DocumentFormModal validation accessibility", () => {
  it("reports a failed save to the accessibility tree, not just in red", () => {
    // Measured after a failed save: zero fields with aria-invalid, zero
    // role="alert", zero messages with an id to point at. A screen reader
    // user pressed Create and nothing happened, with no way to find out why.
    render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Create receipt" }));

    const alerts = screen.getAllByRole("alert");
    expect(alerts.length).toBeGreaterThan(0);

    const invalid = document.querySelectorAll('[aria-invalid="true"]');
    expect(invalid.length).toBeGreaterThan(0);

    // Not only the line inputs: the partner and location pickers carry the
    // same two errors and were reporting neither.
    const partnerPicker = document.getElementById("document-form-partner");
    expect(partnerPicker).toHaveAttribute("aria-invalid", "true");

    for (const field of invalid) {
      const describedBy = field.getAttribute("aria-describedby");
      expect(describedBy).toBeTruthy();
      expect(document.getElementById(describedBy as string)).toBeTruthy();
    }
  });

  it("moves focus to the first field that needs fixing", () => {
    // Focus stayed on the Create button, so the only way to find the problem
    // was to look at the colour of a border.
    render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Create receipt" }));

    const firstInvalid = document.querySelector('[aria-invalid="true"]');
    expect(document.activeElement).toBe(firstInvalid);
  });

  it("asks before throwing away a form the user has filled in", () => {
    // Escape closed the sheet with the partner, location and lines in it,
    // with no warning and no way back.
    const onClose = vi.fn();
    render(<DocumentFormModal initialType="IN" onClose={onClose} />);

    const lineName = screen.getAllByPlaceholderText("Item")[0];
    fireEvent.change(lineName, { target: { value: "Widget" } });

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("closes on Escape when nothing has been entered", () => {
    const onClose = vi.fn();
    render(<DocumentFormModal initialType="IN" onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalled();
  });
});

/**
 * The pickers answer to the module-data policy: they offer the scoped set,
 * and a document already holding module-owned locations keeps them
 * selectable (keepId) so an edit never silently clears where it moves from
 * or to.
 */
describe("DocumentFormModal — which locations the pickers offer", () => {
  const internalShelf = { id: "loc-1", name: "Receiving" };
  const mainShelf = { id: "loc-2", name: "Main Shelf" };
  const moduleRack = {
    id: "loc-rack",
    name: "Server Rack A",
    context_tag: "equipment",
  };

  it("offers the places a stock flow may use, not every location the organization has", async () => {
    locationRequests = serveLocations([internalShelf, moduleRack]);

    await act(async () => {
      render(<DocumentFormModal initialType="INT" onClose={vi.fn()} />);
    });

    // The mocked combobox renders its options as a native select.
    for (const label of [
      "Choose where the goods come from",
      "Choose where the goods go",
    ]) {
      const picker = screen.getByLabelText(label);
      expect(await within(picker).findByText("Receiving")).toBeInTheDocument();
      expect(
        within(picker).queryByText("Server Rack A"),
      ).not.toBeInTheDocument();
    }
    for (const asked of locationRequests) {
      expect(asked.get("exclude_module_contexts")).toBe("true");
    }
  });

  it("opens on the shelf it is handed", async () => {
    serveLocations([internalShelf, mainShelf]);

    await act(async () => {
      render(
        <DocumentFormModal
          initialType="INT"
          initialSourceLocationId="loc-1"
          onClose={vi.fn()}
        />,
      );
    });

    await waitFor(() =>
      expect(
        screen.getByLabelText("Choose where the goods come from"),
      ).toHaveValue("loc-1"),
    );
    expect(screen.getByLabelText("Choose where the goods go")).toHaveValue("");
  });

  it("closes a form it opened from a hold without asking to discard", () => {
    serveLocations([internalShelf, mainShelf]);
    const onClose = vi.fn();

    render(
      <DocumentFormModal
        initialType="INT"
        initialSourceLocationId="loc-1"
        initialLines={[{ item_id: "item-1", name: "Milk", quantity: "3" }]}
        onClose={onClose}
      />,
    );

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalled();
  });

  it("names the document's own locations by id, even those no picker offers", async () => {
    const existing = {
      id: "doc-1",
      organization_id: "org-1",
      type: "INT",
      number: "INT/2026/001",
      status: "DRAFT",
      partner_id: null,
      source_location_id: "loc-rack",
      target_location_id: "loc-2",
      scheduled_date: null,
      notes: null,
      external_reference: null,
      lines: [],
    } as unknown as React.ComponentProps<typeof DocumentFormModal>["document"];
    locationRequests = serveLocations([internalShelf, mainShelf, moduleRack]);

    await act(async () => {
      render(<DocumentFormModal document={existing} onClose={vi.fn()} />);
    });

    // The rack is a module's own place: the stock scope never offers it, and
    // the form still shows where the document moves from.
    await waitFor(() =>
      expect(
        within(
          screen.getByLabelText("Choose where the goods come from"),
        ).getByText("Server Rack A"),
      ).toBeInTheDocument(),
    );
    expect(
      locationRequests.some((asked) =>
        asked.getAll("ids").includes("loc-rack"),
      ),
    ).toBe(true);
  });

  it("keeps the places it last used when the check that they are still on offer failed", async () => {
    window.localStorage.clear();
    rememberLastUsedLocations("IN", "", "loc-2");
    locationRequests = serveLocations([internalShelf, mainShelf]);
    server.use(
      http.get("/api/v1/locations", ({ request }) => {
        const asked = new URL(request.url).searchParams;
        return asked.has("ids") && !asked.has("usage")
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined;
      }),
    );

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });
    await placesLoaded();

    // The check could not be made, which does not say the place is gone.
    await waitFor(() =>
      expect(screen.getByLabelText("Choose where the goods go")).toHaveValue(
        "loc-2",
      ),
    );
    window.localStorage.clear();
  });

  it("names nothing by id for a new document", async () => {
    // Nothing remembered from an earlier document either.
    window.localStorage.clear();
    locationRequests = serveLocations([internalShelf, mainShelf]);

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });
    await placesLoaded();

    expect(locationRequests.every((asked) => !asked.has("ids"))).toBe(true);
  });

  it("puts the single location into the field the document needs", async () => {
    // One place to receive into is no decision — the field says so instead
    // of asking for the click.
    serveLocations([internalShelf]);

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    await waitFor(() =>
      expect(screen.getByLabelText("Choose where the goods go")).toHaveValue(
        "loc-1",
      ),
    );
  });

  it("leaves both ends of a transfer empty when one location cannot fill them", async () => {
    // A transfer names where from and where to; with a single location there
    // is nowhere to transfer to, and one field filled would only say so
    // later, at submit.
    serveLocations([internalShelf]);

    await act(async () => {
      render(<DocumentFormModal initialType="INT" onClose={vi.fn()} />);
    });
    await within(
      screen.getByLabelText("Choose where the goods come from"),
    ).findByText("Receiving");

    expect(
      screen.getByLabelText("Choose where the goods come from"),
    ).toHaveValue("");
    expect(screen.getByLabelText("Choose where the goods go")).toHaveValue("");
  });
});

/**
 * What the form shows about money has to be what the document will carry.
 * Two separate leaks said otherwise: the currency came from the documents
 * profile, which starts empty on every new organization, and the VAT rate
 * the server applies from that same profile never reached the field the
 * user reads before pressing Create.
 */
describe("DocumentFormModal — the amounts it shows are the amounts it saves", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(productSearchHooks.useProductSearch).mockReturnValue({
      results: [],
      isLoading: false,
      error: null,
      search: vi.fn(),
      selectResult: vi.fn(),
      clearSearch: vi.fn(),
      query: "",
      setQuery: vi.fn(),
    } as unknown as ReturnType<typeof productSearchHooks.useProductSearch>);
    vi.mocked(documentHooks.useCreateDocument).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof documentHooks.useCreateDocument>);
    vi.mocked(documentHooks.useUpdateDocument).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof documentHooks.useUpdateDocument>);
    vi.mocked(partnerHooks.usePartners).mockReturnValue({
      data: {
        items: [{ id: "partner-1", name: "ACME Supplies" }],
        total: 1,
      },
    } as unknown as ReturnType<typeof partnerHooks.usePartners>);
    locationRequests = serveLocations(PLACES);
    vi.mocked(itemHooks.useItems).mockReturnValue({
      data: { items: [], total: 0, limit: 15, offset: 0, has_more: false },
    } as unknown as ReturnType<typeof itemHooks.useItems>);
  });

  function serveProfile(overrides: Record<string, unknown>) {
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: {
        id: "profile-1",
        organization_id: "org-1",
        name: "Full Value",
        value_tracking_enabled: true,
        tax_handling: "SIMPLE_RATE",
        default_tax_rate: "20.00",
        require_partner_tax_id: false,
        numbering_format: "{TYPE}/{YEAR}/{SEQ:03d}",
        type_labels: null,
        default_unit: "pcs",
        visible_line_fields: [],
        print_template: "standard",
        // The onboarding preset leaves this empty; the organization's
        // currency is the one that applies.
        default_currency: null,
        created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:00",
        ...overrides,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
  }

  const pricedDocument = {
    id: "doc-1",
    organization_id: "org-1",
    type: "IN",
    number: "IN/2026/001",
    status: "DRAFT",
    partner_id: "partner-1",
    source_location_id: null,
    target_location_id: "loc-1",
    scheduled_date: null,
    notes: null,
    external_reference: null,
    currency: null,
    lines: [
      {
        id: "line-1",
        name: "Widget",
        quantity: 10,
        uom_id: null,
        unit_price: "5.14",
        tax_rate: "20",
      },
    ],
  } as unknown as React.ComponentProps<typeof DocumentFormModal>["document"];

  it("prices the form in the organization's currency, not the profile's empty one", async () => {
    serveProfile({});

    await act(async () => {
      render(<DocumentFormModal document={pricedDocument} onClose={vi.fn()} />);
    });

    // The profile has no currency of its own, so the organization's applies —
    // the same chain the server walks when it stamps the document. Without
    // it every amount on this form read "51.40 ?", which looks like a fault.
    await waitFor(() => {
      expect(screen.getAllByText(/PLN/).length).toBeGreaterThan(0);
    });
    expect(screen.queryByText(/\d\s\?$/)).not.toBeInTheDocument();
  });

  it("lets the profile override the currency when it has one", async () => {
    serveProfile({ default_currency: "EUR" });

    await act(async () => {
      render(<DocumentFormModal document={pricedDocument} onClose={vi.fn()} />);
    });

    await waitFor(() => {
      expect(screen.getAllByText(/€/).length).toBeGreaterThan(0);
    });
  });

  it("totals a blank VAT field at the rate the server will apply", async () => {
    serveProfile({});

    await act(async () => {
      render(
        <DocumentFormModal
          document={
            {
              ...pricedDocument,
              lines: [
                {
                  id: "line-1",
                  name: "Widget",
                  quantity: 10,
                  uom_id: null,
                  unit_price: "5.14",
                  // Nobody typed a rate. The server stamps the profile's 20%.
                  tax_rate: null,
                },
              ],
            } as unknown as React.ComponentProps<
              typeof DocumentFormModal
            >["document"]
          }
          onClose={vi.fn()}
        />,
      );
    });

    // Approved at 51.40, created at 61.68 — the whole of the report.
    await waitFor(() => {
      expect(screen.getAllByText(/61[.,]68/).length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText(/51[.,]40/).length).toBeGreaterThan(0);
  });

  it("says in the field itself which rate a blank means", async () => {
    serveProfile({});
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add line" }));
    });

    // A placeholder, not a value: the field stays empty and editable, and
    // still tells the user what leaving it empty will cost.
    const taxField = document.getElementById(
      "line-item-0-tax-rate",
    ) as HTMLInputElement | null;
    expect(taxField).not.toBeNull();
    expect(taxField?.value).toBe("");
    expect(taxField?.placeholder).toBe("20.00");
  });

  it("leaves the VAT field alone when the profile charges no tax", async () => {
    serveProfile({ tax_handling: "NONE", default_tax_rate: null });
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add line" }));
    });

    // With no tax handling the field is not rendered at all; if it ever is,
    // a blank there really does mean zero and must not suggest otherwise.
    const taxField = document.getElementById(
      "line-item-0-tax-rate",
    ) as HTMLInputElement | null;
    expect(taxField?.value ?? "").toBe("");
    expect(taxField?.placeholder ?? "").toBe("");
  });

  it("keeps price, VAT and the value warning off a transfer", async () => {
    serveProfile({});
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="INT" onClose={vi.fn()} />);
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add line" }));
    });

    // A move between shelves changes where the goods stand, not what they
    // are worth: no price field, no VAT field, and no warning that the
    // document "has no accounting value" — it was never meant to have one.
    expect(screen.queryByText(/unit price/i)).not.toBeInTheDocument();
    expect(document.getElementById("line-item-0-tax-rate")).toBeNull();
    expect(screen.queryByText(/no accounting value/i)).not.toBeInTheDocument();
  });

  it("offers a receipt price, VAT and the empty-price warning", async () => {
    serveProfile({});
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add line" }));
    });

    expect(screen.getAllByText(/unit price/i).length).toBeGreaterThan(0);
    expect(document.getElementById("line-item-0-tax-rate")).not.toBeNull();
    expect(screen.getByText(/no accounting value/i)).toBeInTheDocument();
  });

  it("offers a receipt no price while the profile does not track value", async () => {
    serveProfile({ value_tracking_enabled: false });
    const user = userEvent.setup();

    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add line" }));
    });

    expect(screen.queryByText(/unit price/i)).not.toBeInTheDocument();
    expect(document.getElementById("line-item-0-tax-rate")).toBeNull();
    expect(screen.queryByText(/no accounting value/i)).not.toBeInTheDocument();
  });
});

describe("DocumentFormModal — the empty-price warning speaks for its lines", () => {
  const productWithoutPrice = {
    product_template_id: "tmpl-1",
    item_id: null,
    name: "Mystery Widget",
    sku: "MW-1",
    barcode: null,
    brand: null,
    image_url: null,
    uom_id: "uom-1",
  };
  const productWithPrice = {
    product_template_id: "tmpl-2",
    item_id: null,
    name: "Known Widget",
    sku: "KW-1",
    barcode: null,
    brand: null,
    image_url: null,
    uom_id: "uom-1",
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(productSearchHooks.useProductSearch).mockReturnValue({
      query: "",
      setQuery: vi.fn(),
      results: [productWithoutPrice, productWithPrice],
      isLoading: false,
      error: null,
      search: vi.fn(),
      selectResult: vi.fn(),
      clearSearch: vi.fn(),
    } as unknown as ReturnType<typeof productSearchHooks.useProductSearch>);
    vi.mocked(documentHooks.useCreateDocument).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof documentHooks.useCreateDocument>);
    vi.mocked(documentHooks.useUpdateDocument).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof documentHooks.useUpdateDocument>);
    vi.mocked(partnerHooks.usePartners).mockReturnValue({
      data: { items: [], total: 0 },
    } as unknown as ReturnType<typeof partnerHooks.usePartners>);
    serveLocations([{ id: "loc-1", name: "Receiving" }]);
    vi.mocked(itemHooks.useItems).mockReturnValue({
      data: { items: [], total: 0, limit: 15, offset: 0, has_more: false },
    } as unknown as ReturnType<typeof itemHooks.useItems>);
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: {
        id: "profile-1",
        organization_id: "org-1",
        name: "Simple",
        value_tracking_enabled: true,
        tax_handling: "NONE",
        default_tax_rate: null,
        require_partner_tax_id: false,
        numbering_format: "{TYPE}/{YEAR}/{SEQ:03d}",
        type_labels: null,
        default_unit: "pcs",
        visible_line_fields: [],
        print_template: "standard",
        default_currency: null,
        created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:00",
      },
      isLoading: false,
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
  });

  it("says what the price sources answered under the line they answered for", async () => {
    // One sentence under the table could not be true of a line that asked and
    // found nothing and of an empty line beside it, which has not asked yet.
    const user = userEvent.setup();
    editorStub.enabled = true;
    await act(async () => {
      render(<DocumentFormModal initialType="IN" onClose={vi.fn()} />);
    });
    const [first] = editorStub.lineKeys;
    await user.click(
      screen.getByRole("button", { name: `simulate hint miss for ${first}` }),
    );
    await user.click(screen.getByRole("button", { name: "Add line" }));
    const second = editorStub.lineKeys[1];

    const noPriceSource = /no price in your price books or past purchases/i;
    expect(
      within(screen.getByTestId(`extra ${first}`)).getByText(noPriceSource),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId(`extra ${second}`)).queryByText(noPriceSource),
    ).not.toBeInTheDocument();

    // The sentence under the table speaks of the document alone.
    expect(
      screen.getByText(
        "Some lines have no unit price — this document has no accounting value.",
      ),
    ).toBeInTheDocument();

    // A price typed on the line ends what was said about it.
    await user.click(
      screen.getByRole("button", { name: `price line ${first}` }),
    );
    expect(screen.queryByText(noPriceSource)).not.toBeInTheDocument();
    editorStub.enabled = false;
  });
});

/**
 * A module's own fields on a document reach the form through its slots, and
 * an edit sends them back: saving a draft replaces its lines, so a form that
 * did not carry them would erase what the module wrote.
 */
describe("DocumentFormModal — other modules' fields on the document", () => {
  const updateMutate = vi.fn();
  const existing = {
    id: "doc-1",
    organization_id: "org-1",
    type: "IN",
    number: "DRAFT-1",
    status: "DRAFT",
    partner_id: "partner-1",
    source_location_id: null,
    target_location_id: "loc-1",
    scheduled_date: null,
    notes: null,
    external_reference: null,
    meta_data: { customs: { entry: "PL-77" } },
    lines: [
      {
        id: "line-1",
        product_template_id: "tpl-1",
        name: "Jasmine Rice",
        quantity: "5",
        meta_data: {
          slot_probe: { certificate: "C-1" },
          grading: { grade: "A" },
        },
      },
    ],
  } as unknown as React.ComponentProps<typeof DocumentFormModal>["document"];

  function HeaderField({ data }: { data: SlotDataMap["document_form_extra"] }) {
    return (
      <p>
        {data.action} form, customs entry{" "}
        {String(data.metaData.customs?.entry ?? "none")}
      </p>
    );
  }

  function CertificateField({
    data,
  }: {
    data: SlotDataMap["document_line_form_extra"];
  }) {
    return (
      <label>
        Certificate for {data.line.name}
        <input
          value={String(data.line.metaData.slot_probe?.certificate ?? "")}
          onChange={(event) =>
            data.setMetaData("slot_probe", { certificate: event.target.value })
          }
        />
      </label>
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(productSearchHooks.useProductSearch).mockReturnValue({
      query: "",
      setQuery: vi.fn(),
      results: [],
      isLoading: false,
      error: null,
      search: vi.fn(),
      selectResult: vi.fn(),
      clearSearch: vi.fn(),
    } as unknown as ReturnType<typeof productSearchHooks.useProductSearch>);
    vi.mocked(documentHooks.useCreateDocument).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof documentHooks.useCreateDocument>);
    vi.mocked(documentHooks.useUpdateDocument).mockReturnValue({
      mutate: updateMutate,
      isPending: false,
    } as unknown as ReturnType<typeof documentHooks.useUpdateDocument>);
    vi.mocked(partnerHooks.usePartners).mockReturnValue({
      data: {
        items: [{ id: "partner-1", name: "ACME Supplies" }],
        total: 1,
      },
    } as unknown as ReturnType<typeof partnerHooks.usePartners>);
    serveLocations([{ id: "loc-1", name: "Receiving" }]);
    vi.mocked(itemHooks.useItems).mockReturnValue({
      data: { items: [], total: 0, limit: 15, offset: 0, has_more: false },
    } as unknown as ReturnType<typeof itemHooks.useItems>);
    moduleRegistry.register({
      name: "slot-probe",
      routes: [],
      slots: [
        { slot: "document_form_extra", component: slotComponent(HeaderField) },
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
    } as unknown as ReturnType<typeof modulesCtx.useModules>);
  });

  it("shows the module what it wrote and saves the draft with every module's fields", async () => {
    const user = userEvent.setup();
    await act(async () => {
      render(<DocumentFormModal document={existing} onClose={vi.fn()} />);
    });

    expect(
      screen.getByText("document form, customs entry PL-77"),
    ).toBeInTheDocument();
    const certificate = screen.getByLabelText("Certificate for Jasmine Rice");
    expect(certificate).toHaveValue("C-1");

    await user.clear(certificate);
    await user.type(certificate, "C-2");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(updateMutate).toHaveBeenCalledOnce();
    const sent = updateMutate.mock.calls[0][0].data;
    expect(sent.meta_data).toEqual({ customs: { entry: "PL-77" } });
    expect(sent.lines[0].meta_data).toEqual({
      slot_probe: { certificate: "C-2" },
      grading: { grade: "A" },
    });
  });
});
