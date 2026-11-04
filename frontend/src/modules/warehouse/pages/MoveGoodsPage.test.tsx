import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import * as modulesCtx from "@/contexts/ModulesContext";
import * as mediaQuery from "@/hooks/useMediaQuery";
import * as documentHooks from "@/modules/warehouse/hooks/useDocuments";
import MoveGoodsPage from "./MoveGoodsPage";
import { onePage } from "@/test/mocks/page";
import { serveLocations } from "@/test/serveLocations";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  Toaster: () => null,
}));

vi.mock("@/hooks/useMediaQuery", () => ({ useMediaQuery: vi.fn() }));
vi.mock("@/hooks/useCanWrite", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCanWrite")>()),
  useCanWrite: () => true,
}));
vi.mock("@/hooks/useDocumentCurrency", () => ({
  useDocumentCurrency: () => "USD",
}));
vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: () => ({
    isCameraActive: false,
    scannerError: null,
    isTorchOn: false,
    toggleTorch: vi.fn(),
    restartCamera: vi.fn(),
  }),
}));

vi.mock("@/modules/settings/hooks/useOrganization", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/modules/settings/hooks/useOrganization")
  >()),
  useShowModuleData: () => false,
}));

vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({
    // Value tracking on: a move still offers no price.
    data: { value_tracking_enabled: true, tax_handling: "SIMPLE_RATE" },
  }),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentPartnerOptions", () => ({
  useDocumentPartnerOptions: () => ({
    partnerTypes: [],
    selectedPartnerOffered: true,
    fieldProps: { partners: [], onPartnerSearch: vi.fn() },
  }),
}));

const rice = {
  item_id: "rec-1",
  product_template_id: "pt-rice",
  name: "Jasmine Rice",
  available_quantity: "12",
  location_name: "Shelf A",
  uom_id: null,
  uom_symbol: "pcs",
  is_stub: false,
};

vi.mock("@/modules/warehouse/hooks/useProductSearch", () => ({
  useProductSearch: () => ({
    results: [rice],
    elsewhere: [],
    isLoading: false,
    error: null,
    search: vi.fn(),
    selectResult: vi.fn(),
    clearSearch: vi.fn(),
    query: "",
    setQuery: vi.fn(),
  }),
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  usePostNewDocument: vi.fn(),
  useUndoDocument: () => ({ mutate: vi.fn(), isPending: false }),
}));

// A native <select> stands in for the searchable picker.
vi.mock("@/components/ui/SearchableCombobox", () => ({
  SearchableCombobox: ({
    options,
    value,
    onChange,
    label,
    error,
    id,
  }: {
    options: { id: string; name: string }[];
    value: string;
    onChange: (v: string) => void;
    label?: string;
    error?: string;
    id?: string;
  }) => (
    <div>
      <select
        id={id}
        aria-label={label}
        aria-invalid={error ? true : undefined}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">—</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
      {error && <p role="alert">{error}</p>}
    </div>
  ),
}));

const postMutate = vi.fn();

function renderPage() {
  const header = { data: { title: "", actions: null }, setHeader: vi.fn() };
  return render(
    <PageHeaderContext.Provider value={header}>
      <MoveGoodsPage />
    </PageHeaderContext.Provider>,
  );
}

function record(id: string, name: string, quantity: number) {
  return {
    id,
    name,
    quantity,
    uom_id: null,
    location_id: "shelf-a",
    template_id: `pt-${id}`,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  serveLocations([
    {
      id: "wh",
      name: "Main Warehouse",
      direct_children_count: 1,
      is_leaf: false,
    },
    { id: "shelf-a", name: "Shelf A", parent_id: "wh" },
  ]);
  vi.mocked(mediaQuery.useMediaQuery).mockReturnValue(false);
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["warehouse"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  } as unknown as ReturnType<typeof modulesCtx.useModules>);
  vi.mocked(documentHooks.usePostNewDocument).mockReturnValue({
    mutate: postMutate,
    isPending: false,
  } as unknown as ReturnType<typeof documentHooks.usePostNewDocument>);
  server.use(
    http.get("/api/v1/locations/shelf-a/items", () =>
      HttpResponse.json(
        onePage([
          record("rec-1", "Jasmine Rice", 12),
          record("rec-2", "Rolled Oats", 4),
          record("rec-empty", "Cane Sugar", 0),
        ]),
      ),
    ),
  );
});

describe("MoveGoodsPage", () => {
  it("moves everything standing on a shelf, each record whole, in one post", async () => {
    const user = userEvent.setup();
    postMutate.mockImplementation((_payload, options) =>
      options.onSuccess({
        id: "doc-2",
        number: "INT/2026/004",
        type: "INT",
        status: "COMPLETED",
        lines: [],
      }),
    );
    renderPage();
    await screen.findAllByRole("option", { name: "Shelf A" });

    await user.selectOptions(
      screen.getByRole("combobox", { name: "From location" }),
      "shelf-a",
    );
    await user.click(
      screen.getByRole("button", { name: "Everything in Shelf A" }),
    );
    expect(await screen.findByText("2 lines")).toBeInTheDocument();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "To location" }),
      "wh",
    );

    expect(
      screen.queryByRole("button", { name: "Add prices for accounting" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Move" }));

    expect(postMutate).toHaveBeenCalledOnce();
    const payload = postMutate.mock.calls[0][0].data;
    expect(payload).toMatchObject({
      type: "INT",
      source_location_id: "shelf-a",
      target_location_id: "wh",
      lines: [
        { item_id: "rec-1", expected_quantity: 12 },
        { item_id: "rec-2", expected_quantity: 4 },
      ],
    });
    expect(payload.partner_id).toBeUndefined();
    expect(
      payload.lines.every(
        (line: { unit_price?: string }) => line.unit_price === undefined,
      ),
    ).toBe(true);
    expect(
      await screen.findByRole("heading", { name: "Moved 2 lines" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo move" })).toBeVisible();
  });

  it("offers everything only for a location nothing else sits in", async () => {
    // The button reads the records standing on the source itself; offered
    // for a warehouse whose shelves hold the stock it answered "Nothing more
    // stands in Main Warehouse" over full shelves.
    const user = userEvent.setup();
    renderPage();
    await screen.findAllByRole("option", { name: "Shelf A" });

    await user.selectOptions(
      screen.getByRole("combobox", { name: "From location" }),
      "wh",
    );
    expect(
      screen.queryByRole("button", { name: /^Everything in/ }),
    ).not.toBeInTheDocument();

    await user.selectOptions(
      screen.getByRole("combobox", { name: "From location" }),
      "shelf-a",
    );
    expect(
      screen.getByRole("button", { name: "Everything in Shelf A" }),
    ).toBeInTheDocument();
  });

  it("asks where the goods go before posting", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findAllByRole("option", { name: "Shelf A" });

    await user.selectOptions(
      screen.getByRole("combobox", { name: "From location" }),
      "shelf-a",
    );
    await user.click(
      screen.getByRole("button", { name: "Everything in Shelf A" }),
    );
    await screen.findByText("2 lines");
    await user.click(screen.getByRole("button", { name: "Move" }));

    expect(postMutate).not.toHaveBeenCalled();
    expect(
      screen.getByRole("combobox", { name: "To location" }),
    ).toHaveAttribute("aria-invalid", "true");
    // The screen names no document type, so the shared check's sentence
    // about one would be a riddle.
    expect(
      screen.getByText("Choose the location the goods go to."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/is required for this document type/),
    ).not.toBeInTheDocument();
  });

  it("names the place the goods come from when it is left empty", async () => {
    const user = userEvent.setup();
    // Two warehouses and none remembered: no source is picked for the reader.
    serveLocations([
      { id: "wh", name: "Main Warehouse" },
      { id: "cold", name: "Cold Store" },
    ]);
    renderPage();
    await screen.findAllByRole("option", { name: "Cold Store" });

    await user.click(screen.getByRole("button", { name: "Move" }));

    expect(
      screen.getByText("Choose the location the goods come from."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/is required for this document type/),
    ).not.toBeInTheDocument();
  });
});
