import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { buildGridClass, LineItemsEditor } from "./LineItemsEditor";
import { formatDate } from "@/utils/formatters";
import type {
  LineItem,
  LineItemsEditorFeatures,
  LineItemsEditorLabels,
  LineItemsScanState,
} from "./types";

const torch = vi.hoisted(() => ({ available: true }));
vi.mock("@/hooks/useTorchAvailable", () => ({
  useTorchAvailable: () => torch.available,
}));

const makeLabels = (): LineItemsEditorLabels => ({
  lines: "Lines",
  addLine: "Add Line",
  scanOpen: "Scan",
  scanClose: "Close scan",
  scanHint: "Point camera at barcode",
  torchOn: "Torch on",
  torchOff: "Torch off",
  emptyHint: "Search for existing items",
  item: "Item",
  quantity: "Quantity",
  unit: "Unit",
  unitPrice: "Unit Price",
  lineValue: "Net Value",
  taxRate: "VAT %",
  removeLine: "Remove line",
  clearProduct: "Clear",
  noResults: "No results found",
  showOptionalFields: "More fields",
  hideOptionalFields: "Fewer fields",
  consolidate: "Consolidate",
  batchNumber: "Batch Number",
  serialNumber: "Serial Number",
  expiryDate: "Expiry Date",
  expiryFieldHiddenHint: "Hidden",
  showExpiryField: "Add Expiry Date",
  hideExpiryField: "Hide Expiry Date",
  notes: "Notes",
  subtotal: "Net",
  taxAmount: "VAT",
  total: "Gross",
});

const makeScan = (
  overrides: Partial<LineItemsScanState> = {},
): LineItemsScanState => ({
  open: false,
  loading: false,
  error: null,
  cameraActive: false,
  torchOn: false,
  onToggle: vi.fn(),
  onToggleTorch: vi.fn(),
  ...overrides,
});

const makeLine = (overrides: Partial<LineItem> = {}): LineItem => ({
  key: "k1",
  name: "Widget",
  quantity: 5,
  ...overrides,
});

const makeProps = () => ({
  lines: [makeLine()],
  mode: "document" as const,
  features: { scan: true, optionalFields: true, consolidate: true },
  labels: makeLabels(),
  totalsCurrency: "PLN",
  search: {
    results: [],
    isLoading: false,
    onQuery: vi.fn(),
    onClear: vi.fn(),
  },
  renderUomSelect: () => null,
  testIds: {
    shell: "document-lines-table-shell",
    desktopHeader: "document-lines-desktop-header",
    rowLayout: (i: number) => `document-line-card-layout-${i}`,
    optionalPanel: (i: number) => `document-line-optional-panel-${i}`,
  },
  onAddLine: vi.fn(),
  onRemoveLine: vi.fn(),
  onUpdateLine: vi.fn(),
  onSelectProduct: vi.fn(),
});

describe("buildGridClass (Tailwind JIT static literals)", () => {
  // Full literals Tailwind JIT can see. Keep this list in sync with
  // GRID_COLUMN_CLASSES in LineItemsEditor.tsx — if a composed class ever
  // sneaks back in, the result stops matching a literal here and fails.
  const KNOWN_LITERALS = [
    "xl:grid-cols-[minmax(0,1fr)_110px_100px_40px]",
    "xl:grid-cols-[minmax(0,1fr)_110px_100px_40px_20px]",
    "xl:grid-cols-[minmax(0,1fr)_110px_100px_110px_110px_40px]",
    "xl:grid-cols-[minmax(0,1fr)_110px_100px_110px_110px_40px_20px]",
    "xl:grid-cols-[minmax(0,1fr)_110px_100px_110px_90px_110px_40px]",
    "xl:grid-cols-[minmax(0,1fr)_110px_100px_110px_90px_110px_40px_20px]",
  ] as const;

  it("returns a pre-existing literal for every feature combination", () => {
    const combinations: Array<[string, LineItemsEditorFeatures]> = [
      ["no value fields, no optional", {}],
      ["no value fields, optional", { optionalFields: true }],
      ["value fields, no tax, no optional", { valueFields: true }],
      [
        "value fields, no tax, optional",
        { valueFields: true, optionalFields: true },
      ],
      ["value fields, tax, no optional", { valueFields: true, taxField: true }],
      [
        "value fields, tax, optional",
        { valueFields: true, taxField: true, optionalFields: true },
      ],
    ];
    for (const [label, features] of combinations) {
      const cls = buildGridClass(features);
      expect(
        KNOWN_LITERALS,
        `combination "${label}" produced non-literal class "${cls}"`,
      ).toContain(cls);
    }
  });

  it("taxField has no effect when valueFields is off", () => {
    expect(buildGridClass({ taxField: true })).toBe(buildGridClass({}));
  });
});

describe("LineItemsEditor", () => {
  it("shows empty state when no lines", () => {
    const props = makeProps();
    render(<LineItemsEditor {...props} lines={[]} />);
    expect(screen.getByText(/search for existing items/i)).toBeInTheDocument();
  });

  it("renders rows when lines exist", () => {
    const props = makeProps();
    render(
      <LineItemsEditor
        {...props}
        lines={[makeLine({ product_template_id: "pt-1" })]}
      />,
    );
    expect(
      screen.getByTestId("document-line-card-layout-0"),
    ).toBeInTheDocument();
    expect(screen.getByText("Widget")).toBeInTheDocument();
  });

  it("shows desktop header when lines exist", () => {
    const props = makeProps();
    render(<LineItemsEditor {...props} />);
    expect(
      screen.getByTestId("document-lines-desktop-header"),
    ).toBeInTheDocument();
  });

  it("calls onAddLine when Add Line is clicked", async () => {
    const props = makeProps();
    const user = userEvent.setup();
    render(<LineItemsEditor {...props} />);
    await user.click(screen.getByRole("button", { name: /add line/i }));
    expect(props.onAddLine).toHaveBeenCalledOnce();
  });

  it("toggles scan from the scan button", async () => {
    const scan = makeScan();
    const props = makeProps();
    const user = userEvent.setup();
    render(<LineItemsEditor {...props} scan={scan} />);
    await user.click(screen.getByRole("button", { name: /scan/i }));
    expect(scan.onToggle).toHaveBeenCalledOnce();
  });

  it("shows scanner hint when scan is open", () => {
    const scan = makeScan({ open: true, cameraActive: true });
    const props = makeProps();
    render(<LineItemsEditor {...props} scan={scan} />);
    expect(screen.getByText(/point camera at barcode/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Torch on" }),
    ).toBeInTheDocument();
  });

  it("draws no second aim box and keeps the torch inside the camera box", () => {
    const scan = makeScan({ open: true, cameraActive: true });
    const props = makeProps();
    render(<LineItemsEditor {...props} scan={scan} />);
    expect(screen.queryByTestId("scan-reticle")).not.toBeInTheDocument();
    const box = screen.getByTestId("scan-camera-box");
    expect(box).toContainElement(
      screen.getByRole("button", { name: "Torch on" }),
    );
    expect(box).toContainElement(document.getElementById("qr-reader"));
  });

  it("draws no torch button on a camera that has no torch", () => {
    torch.available = false;
    const scan = makeScan({ open: true, cameraActive: true });
    render(<LineItemsEditor {...makeProps()} scan={scan} />);
    torch.available = true;
    expect(
      screen.queryByRole("button", { name: "Torch on" }),
    ).not.toBeInTheDocument();
  });

  it("narrows the camera box so the square camera cannot fill a desktop dialog", () => {
    const scan = makeScan({ open: true, cameraActive: true });
    const props = makeProps();
    render(<LineItemsEditor {...props} scan={scan} />);
    // The camera is a square, so its height is the box's width, and the
    // torch is positioned against the box: both narrow with the video.
    expect(screen.getByTestId("scan-camera-box")).toHaveClass(
      "max-w-sm",
      "mx-auto",
    );
  });

  it("shows the opening notice and no torch while the camera is still opening", () => {
    const scan = makeScan({ open: true, cameraActive: false });
    const props = makeProps();
    render(<LineItemsEditor {...props} scan={scan} />);
    expect(
      screen.queryByRole("button", { name: "Torch on" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/opening camera/i)).toBeInTheDocument();
  });

  it("renders scan processing indicator when a code is being looked up", () => {
    const scan = makeScan({
      open: true,
      cameraActive: true,
      loading: true,
    });
    const props = makeProps();
    render(<LineItemsEditor {...props} scan={scan} />);
    expect(screen.getByTestId("scan-processing")).toBeInTheDocument();
  });

  it("shows scanner error when present", () => {
    const scan = makeScan({ open: true, error: "Camera access denied" });
    const props = makeProps();
    render(<LineItemsEditor {...props} scan={scan} />);
    expect(screen.getByText("Camera access denied")).toBeInTheDocument();
  });

  it("renders the quick add slot when provided", () => {
    const props = makeProps();
    render(
      <LineItemsEditor
        {...props}
        features={{ ...props.features, quickAdd: true }}
        quickAddPanel={<div data-testid="quick-add-panel" />}
      />,
    );
    expect(screen.getByTestId("quick-add-panel")).toBeInTheDocument();
  });

  it("shows consolidate button when duplicates exist and onConsolidate provided", () => {
    const props = makeProps();
    render(
      <LineItemsEditor
        {...props}
        lines={[
          makeLine({ key: "k1", item_id: "i1" }),
          makeLine({ key: "k2", item_id: "i1" }),
        ]}
        onConsolidate={vi.fn()}
      />,
    );
    expect(screen.getByText(/consolidate/i)).toBeInTheDocument();
  });

  it("hides consolidate button when no duplicates", () => {
    const props = makeProps();
    render(<LineItemsEditor {...props} onConsolidate={vi.fn()} />);
    expect(screen.queryByText(/consolidate/i)).not.toBeInTheDocument();
  });

  it("shows value columns when valueFields is on", () => {
    const props = makeProps();
    render(
      <LineItemsEditor
        {...props}
        features={{ ...props.features, valueFields: true }}
      />,
    );
    expect(screen.getAllByText(/unit price/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/net value/i).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/vat/i)).toHaveLength(0);
  });

  it("shows tax column when valueFields and taxField are on", () => {
    const props = makeProps();
    render(
      <LineItemsEditor
        {...props}
        features={{ ...props.features, valueFields: true, taxField: true }}
      />,
    );
    expect(screen.getAllByText(/vat/i).length).toBeGreaterThan(0);
  });

  it("shows totals footer when totals are provided and non-zero", () => {
    const props = makeProps();
    render(
      <LineItemsEditor
        {...props}
        features={{ ...props.features, totals: true }}
        totals={{ subtotal: "110.00", tax: "25.30", total: "135.30" }}
      />,
    );
    expect(screen.getByText("PLN 110.00")).toBeInTheDocument();
    expect(screen.getByText("PLN 25.30")).toBeInTheDocument();
    expect(screen.getByText("PLN 135.30")).toBeInTheDocument();
  });

  it("hides totals footer when subtotal is zero", () => {
    const props = makeProps();
    render(
      <LineItemsEditor
        {...props}
        features={{ ...props.features, totals: true }}
        totals={{ subtotal: "0.00", tax: "0.00", total: "0.00" }}
      />,
    );
    expect(screen.queryByText("135.30")).not.toBeInTheDocument();
  });
});

describe("LineItemsEditor (line error contract)", () => {
  it("renders a name error under the name input when lineErrors has name for that line", () => {
    const props = makeProps();
    render(
      <LineItemsEditor
        {...props}
        lines={[makeLine({ key: "k1" })]}
        lineErrors={{ k1: { name: "Name is required" } }}
      />,
    );
    expect(screen.getByText("Name is required")).toBeInTheDocument();
  });

  it("renders a quantity error under the quantity input when lineErrors has quantity for that line", () => {
    const props = makeProps();
    render(
      <LineItemsEditor
        {...props}
        lines={[makeLine({ key: "k1" })]}
        lineErrors={{ k1: { quantity: "Quantity must be greater than zero" } }}
      />,
    );
    expect(
      screen.getByText("Quantity must be greater than zero"),
    ).toBeInTheDocument();
  });

  it("renders no error text when lineErrors is undefined", () => {
    const props = makeProps();
    render(<LineItemsEditor {...props} />);
    expect(screen.queryByText("Name is required")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Quantity must be greater than zero"),
    ).not.toBeInTheDocument();
  });
});

describe("LineItemsEditor (a chosen product still shows its line's error)", () => {
  it("renders the name error next to the product chip", () => {
    const props = makeProps();
    render(
      <LineItemsEditor
        {...props}
        lines={[makeLine({ key: "k1", product_template_id: "tpl-1" })]}
        lineErrors={{ k1: { name: "Dispatch lines must reference items" } }}
      />,
    );
    // The chip replaces the input, so the error has to live beside the chip —
    // otherwise the row shows nothing wrong and only a toast says why.
    expect(screen.getByTestId("line-item-product-error-0")).toHaveTextContent(
      "Dispatch lines must reference items",
    );
  });

  it("shows how much of a stock hit stands in the location", async () => {
    const user = userEvent.setup();
    const props = makeProps();
    render(
      <LineItemsEditor
        {...props}
        lines={[makeLine({ key: "k1", name: "" })]}
        labels={{ ...makeLabels(), inStock: "In stock" }}
        search={{
          results: [
            {
              product_template_id: null,
              item_id: "item-1",
              available_quantity: 7,
              uom_symbol: "pcs",
              name: "Bolt M8 crate",
              sku: null,
              barcode: null,
              brand: null,
              image_url: null,
              uom_id: null,
            },
          ],
          isLoading: false,
          onQuery: vi.fn(),
          onClear: vi.fn(),
        }}
      />,
    );
    await user.click(screen.getByPlaceholderText("Item"));
    expect(await screen.findByText(/In stock: 7 pcs/)).toBeInTheDocument();
  });

  it("says when a stock hit landed, so twins differ by more than quantity", async () => {
    // A shelf holding two unmarked records of one product used to offer
    // two rows differing by nothing but their quantity. The landing date
    // is the row's third word — and a row without a date carries none.
    const user = userEvent.setup();
    const props = makeProps();
    const stockHit = {
      product_template_id: null,
      item_id: "item-1",
      available_quantity: 7,
      uom_symbol: "pcs",
      name: "Bolt M8 crate",
      sku: null,
      barcode: null,
      brand: null,
      image_url: null,
      uom_id: null,
    };
    render(
      <LineItemsEditor
        {...props}
        lines={[makeLine({ key: "k1", name: "" })]}
        labels={{ ...makeLabels(), inStock: "In stock", addedLabel: "Added" }}
        search={{
          results: [
            { ...stockHit, created_at: "2026-09-01T08:00:00Z" },
            {
              ...stockHit,
              item_id: "item-2",
              available_quantity: 3,
              created_at: null,
            },
          ],
          isLoading: false,
          onQuery: vi.fn(),
          onClear: vi.fn(),
        }}
      />,
    );
    await user.click(screen.getByPlaceholderText("Item"));

    const row = await screen.findByText(/^Added: /);
    // The label rides the reader's calendar day — the same formatter every
    // other date on screen uses, never a raw timestamp.
    expect(row.textContent).toBe(
      `Added: ${formatDate("2026-09-01T08:00:00Z")}`,
    );
    // The twin with no date on its record gets no fake one.
    expect(screen.queryByText(/^Added: $/)).not.toBeInTheDocument();
  });
});
