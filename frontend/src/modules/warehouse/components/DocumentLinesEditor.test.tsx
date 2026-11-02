import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { DocumentLinesEditor } from "./DocumentLinesEditor";
import type { ReceiptDraftLine, QuickAddLineDraft } from "./documentFormShared";

const { searchResults, elsewhereResults, priceHint } = vi.hoisted(() => ({
  searchResults: { current: [] as unknown[] },
  elsewhereResults: { current: [] as unknown[] },
  priceHint: vi.fn(),
}));

vi.mock("@/modules/warehouse/hooks/useProductSearch", () => ({
  useProductSearch: () => ({
    results: searchResults.current,
    elsewhere: elsewhereResults.current,
    isLoading: false,
    search: vi.fn(),
    clearSearch: vi.fn(),
  }),
}));

vi.mock("@/modules/warehouse/api/documents", () => ({
  documentsApi: { priceHint },
}));

vi.mock("@/modules/shared/components/UomSelect", () => ({
  UomSelect: ({ value }: { value: string | null }) => (
    <div data-testid="uom-select-stub">{value ?? "no-uom"}</div>
  ),
}));

vi.mock("@/modules/warehouse/components/DocumentQuickAddPanel", () => ({
  DocumentQuickAddPanel: ({
    onSubmit,
    onCancel,
  }: {
    onSubmit: () => void;
    onCancel: () => void;
  }) => (
    <div data-testid="quick-add-panel">
      <button onClick={onSubmit}>Submit Quick Add</button>
      <button onClick={onCancel}>Cancel Quick Add</button>
    </div>
  ),
}));

const defaultCallbacks = {
  onAddEmptyLine: vi.fn(),
  onConsolidate: vi.fn(),
  onQuickAddChange: vi.fn(),
  onQuickAddSubmit: vi.fn(),
  onQuickAddCancel: vi.fn(),
  onScanToggle: vi.fn(),
  onToggleTorch: vi.fn(),
  onManualCode: vi.fn(),
  onRemoveLine: vi.fn(),
  onUpdateLine: vi.fn(),
};

const emptyLine: ReceiptDraftLine = {
  _key: "k1",
  name: "Widget",
  quantity: 5,
  batch_number: "",
  expiry_date: "",
  notes: "",
};

const draftQuickAdd: QuickAddLineDraft = {
  name: "",
  brand: "",
  barcode: "",
  sku: "",
  quantity: 1,
  batch_number: "",
  expiry_date: "",
  notes: "",
};

function renderEditor(
  overrides: Partial<Parameters<typeof DocumentLinesEditor>[0]> = {},
) {
  return render(
    <DocumentLinesEditor
      lines={[emptyLine]}
      quickAddOpen={false}
      quickAddValue={draftQuickAdd}
      scanOpen={false}
      scanLoading={false}
      scannerError={null}
      isCameraActive={false}
      isTorchOn={false}
      {...defaultCallbacks}
      {...overrides}
    />,
  );
}

describe("DocumentLinesEditor", () => {
  it("takes a typed code in the scan panel, so a camera-less desk can scan", async () => {
    const onManualCode = vi.fn();
    renderEditor({ scanOpen: true, onManualCode });

    const input = screen.getByTestId("line-items-manual-code");
    await userEvent.type(input, "5901234123457{Enter}");

    expect(onManualCode).toHaveBeenCalledWith("5901234123457");
  });

  it("keeps the typed code reachable when the camera itself failed", async () => {
    const onManualCode = vi.fn();
    renderEditor({
      scanOpen: true,
      scannerError: "Camera permission denied",
      onManualCode,
    });

    expect(screen.getByTestId("scan-error")).toBeInTheDocument();
    await userEvent.type(
      screen.getByTestId("line-items-manual-code"),
      "STM-0001{Enter}",
    );
    expect(onManualCode).toHaveBeenCalledWith("STM-0001");
  });

  it("shows empty state when no lines", () => {
    renderEditor({ lines: [] });
    expect(screen.getByText(/search for existing items/i)).toBeInTheDocument();
  });

  it("renders line rows when lines exist", () => {
    renderEditor();
    expect(
      screen.getByTestId("document-line-card-layout-0"),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("Widget")).toBeInTheDocument();
  });

  it("renders multiple line rows", () => {
    const line2: ReceiptDraftLine = {
      ...emptyLine,
      _key: "k2",
      name: "Gadget",
    };
    renderEditor({ lines: [emptyLine, line2] });
    expect(
      screen.getByTestId("document-line-card-layout-0"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("document-line-card-layout-1"),
    ).toBeInTheDocument();
  });

  it("calls onAddEmptyLine when Add Line is clicked", async () => {
    const onAddEmptyLine = vi.fn();
    const user = userEvent.setup();
    renderEditor({ onAddEmptyLine });
    await user.click(screen.getByRole("button", { name: /add line/i }));
    expect(onAddEmptyLine).toHaveBeenCalledOnce();
  });

  it("calls onScanToggle when scan button is clicked", async () => {
    const onScanToggle = vi.fn();
    const user = userEvent.setup();
    renderEditor({ onScanToggle });
    await user.click(screen.getByRole("button", { name: /scan/i }));
    expect(onScanToggle).toHaveBeenCalledOnce();
  });

  it("shows scanner area when scanOpen is true", () => {
    renderEditor({ scanOpen: true, isCameraActive: true });
    expect(screen.getByText(/point camera at barcode/i)).toBeInTheDocument();
  });

  it("shows scanner error when present", () => {
    renderEditor({ scanOpen: true, scannerError: "Camera access denied" });
    expect(screen.getByText("Camera access denied")).toBeInTheDocument();
  });

  it("shows quick add panel when quickAddOpen is true", () => {
    renderEditor({ quickAddOpen: true });
    expect(screen.getByTestId("quick-add-panel")).toBeInTheDocument();
  });

  it("shows consolidate button when duplicates exist and onConsolidate provided", () => {
    const line1: ReceiptDraftLine = { ...emptyLine, _key: "k1", item_id: "i1" };
    const line2: ReceiptDraftLine = { ...emptyLine, _key: "k2", item_id: "i1" };
    renderEditor({ lines: [line1, line2] });
    expect(screen.getByText(/consolidate/i)).toBeInTheDocument();
  });

  it("hides consolidate button when no duplicates", () => {
    renderEditor();
    expect(screen.queryByText(/consolidate/i)).not.toBeInTheDocument();
  });

  it("shows desktop header when lines exist", () => {
    renderEditor();
    expect(
      screen.getByTestId("document-lines-desktop-header"),
    ).toBeInTheDocument();
  });

  it("shows value columns when showValueFields is true", () => {
    renderEditor({ showValueFields: true });
    expect(screen.getAllByText(/unit price/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/net value/i).length).toBeGreaterThan(0);
  });

  it("shows tax column when both showValueFields and showTaxField are true", () => {
    renderEditor({ showValueFields: true, showTaxField: true });
    expect(screen.getAllByText(/vat/i).length).toBeGreaterThan(0);
  });

  it("shows torch toggle when scan open and camera active", () => {
    renderEditor({ scanOpen: true, isCameraActive: true });
    expect(
      screen.getByRole("button", { name: /torch on/i }),
    ).toBeInTheDocument();
  });

  it("shows close scan button when scan is open", () => {
    renderEditor({ scanOpen: true });
    expect(screen.getByText(/close/i)).toBeInTheDocument();
  });

  it("maps row updates back to index-based callbacks", async () => {
    const onUpdateLine = vi.fn();
    const user = userEvent.setup();
    renderEditor({ onUpdateLine });
    const nameInput = screen.getByDisplayValue("Widget");
    await user.clear(nameInput);
    await user.type(nameInput, "Gadget");
    expect(onUpdateLine).toHaveBeenCalled();
    const calls = onUpdateLine.mock.calls as [
      number,
      Partial<ReceiptDraftLine>,
    ][];
    const [index, updates] = calls[calls.length - 1];
    expect(index).toBe(0);
    expect(updates).toHaveProperty("name");
  });

  it("maps row remove back to index-based callback", async () => {
    const onRemoveLine = vi.fn();
    const user = userEvent.setup();
    renderEditor({ onRemoveLine });
    const removeButtons = screen.getAllByRole("button", {
      name: "Remove",
    });
    await user.click(removeButtons[0]);
    expect(onRemoveLine).toHaveBeenCalledWith(0);
  });

  it("shows live Net/VAT/Gross totals when value fields are enabled", () => {
    const priced: ReceiptDraftLine = {
      ...emptyLine,
      quantity: 2,
      unit_price: "10.00",
      tax_rate: "23",
    };
    renderEditor({
      lines: [priced],
      showValueFields: true,
      showTaxField: true,
      currency: "PLN",
    });
    expect(screen.getByText(/net total/i)).toBeInTheDocument();
    expect(screen.getByText(/gross total/i)).toBeInTheDocument();
    // 2 × 10.00 = 20.00 net, 4.60 VAT, 24.60 gross
    expect(screen.getAllByText(/20[.,]00/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/24[.,]60/).length).toBeGreaterThan(0);
  });

  it("hides totals when showValueFields is false", () => {
    const priced: ReceiptDraftLine = {
      ...emptyLine,
      quantity: 2,
      unit_price: "10.00",
      tax_rate: "23",
    };
    renderEditor({ lines: [priced], currency: "PLN" });
    expect(screen.queryByText(/net total/i)).not.toBeInTheDocument();
  });

  it("updates totals live when line props change", () => {
    const priced: ReceiptDraftLine = {
      ...emptyLine,
      quantity: 2,
      unit_price: "10.00",
      tax_rate: "0",
    };
    const { rerender } = renderEditor({
      lines: [priced],
      showValueFields: true,
      currency: "PLN",
    });
    expect(screen.getAllByText(/20[.,]00/).length).toBeGreaterThan(0);

    rerender(
      <DocumentLinesEditor
        lines={[{ ...priced, quantity: 5 }]}
        quickAddOpen={false}
        quickAddValue={draftQuickAdd}
        scanOpen={false}
        scanLoading={false}
        scannerError={null}
        isCameraActive={false}
        isTorchOn={false}
        showValueFields={true}
        currency="PLN"
        {...defaultCallbacks}
      />,
    );
    expect(screen.getAllByText(/50[.,]00/).length).toBeGreaterThan(0);
  });
});

/**
 * The suggestion endpoint answers with a price *and* a rate. The client
 * threw both away whenever the price was missing, which is the common case
 * for a product nobody has bought yet — and the rate it dropped was the
 * partner's, the most specific one the system has.
 */
describe("DocumentLinesEditor — what it keeps from a price suggestion", () => {
  const product = {
    product_template_id: "tmpl-1",
    item_id: null,
    name: "Widget",
    sku: "W-1",
    barcode: null,
    brand: null,
    image_url: null,
    uom_id: "uom-1",
  };

  async function selectTheProduct(
    onUpdateLine: Mock,
    onPriceHintResult?: (key: string, suggested: boolean) => void,
    productOverride: Partial<typeof product> = {},
  ) {
    searchResults.current = [{ ...product, ...productOverride }];
    const user = userEvent.setup();
    renderEditor({
      lines: [{ ...emptyLine, name: "" }],
      showValueFields: true,
      showTaxField: true,
      currency: "PLN",
      onUpdateLine,
      onPriceHintResult,
    });
    await user.type(screen.getAllByPlaceholderText("Item")[0], "Wid");
    await user.click(screen.getAllByRole("option")[0]);
  }

  it("keeps the suggested rate even when there is no suggested price", async () => {
    priceHint.mockResolvedValue({ unit_price: null, tax_rate: 23 });
    const onUpdateLine = vi.fn();

    await selectTheProduct(onUpdateLine);

    await vi.waitFor(() => {
      expect(onUpdateLine).toHaveBeenCalledWith(
        0,
        expect.objectContaining({ tax_rate: "23" }),
      );
    });
  });

  it("still fills the price when the suggestion carries one", async () => {
    priceHint.mockResolvedValue({ unit_price: 5.14, tax_rate: 23 });
    const onUpdateLine = vi.fn();

    await selectTheProduct(onUpdateLine);

    await vi.waitFor(() => {
      expect(onUpdateLine).toHaveBeenCalledWith(
        0,
        expect.objectContaining({ unit_price: "5.14", tax_rate: "23" }),
      );
    });
  });

  it("reports a kept promise when the suggestion carries a price", async () => {
    // The empty-price warning promises a suggestion; whether that promise
    // can be kept is exactly what the editor learns here and passes up.
    priceHint.mockResolvedValue({ unit_price: 5.14, tax_rate: 23 });
    const reported = vi.fn();
    await selectTheProduct(vi.fn(), reported);
    await vi.waitFor(() =>
      expect(reported).toHaveBeenCalledWith(expect.any(String), true),
    );
  });

  it("reports an empty price book when nothing came back", async () => {
    priceHint.mockResolvedValue({ unit_price: null, tax_rate: null });
    const reported = vi.fn();
    await selectTheProduct(vi.fn(), reported);
    await vi.waitFor(() =>
      expect(reported).toHaveBeenCalledWith(expect.any(String), false),
    );
  });

  it("reports the ask as answered when the suggestion request fails", async () => {
    // A rejected ask was made all the same — the warning above the form may
    // not keep promising a suggestion for a line that already went looking
    // and got an error back.
    priceHint.mockRejectedValue(new Error("hint lookup failed"));
    const reported = vi.fn();
    await selectTheProduct(vi.fn(), reported);
    await vi.waitFor(() =>
      expect(reported).toHaveBeenCalledWith(expect.any(String), false),
    );
  });

  it("counts a hand-named product as asked when no catalogue entry exists", async () => {
    // Without a template there is nothing to hint from: the answer is known
    // before asking, and the line counts as asked.
    priceHint.mockResolvedValue({ unit_price: 5.14, tax_rate: 23 });
    const reported = vi.fn();
    await selectTheProduct(vi.fn(), reported, {
      product_template_id: undefined,
    });
    await vi.waitFor(() =>
      expect(reported).toHaveBeenCalledWith(expect.any(String), false),
    );
    expect(priceHint).not.toHaveBeenCalled();
  });

  it("asks for no suggestion where the form shows no price", async () => {
    // A transfer hides its price; a hint written into the hidden field would
    // store a value nobody saw.
    priceHint.mockResolvedValue({ unit_price: 5.14, tax_rate: 23 });
    const onUpdateLine = vi.fn();
    const reported = vi.fn();
    searchResults.current = [product];
    const user = userEvent.setup();
    renderEditor({
      lines: [{ ...emptyLine, name: "" }],
      showValueFields: false,
      onUpdateLine,
      onPriceHintResult: reported,
    });
    await user.type(screen.getAllByPlaceholderText("Item")[0], "Wid");
    await user.click(screen.getAllByRole("option")[0]);

    await vi.waitFor(() =>
      expect(reported).toHaveBeenCalledWith(expect.any(String), false),
    );
    expect(priceHint).not.toHaveBeenCalled();
    for (const [, updates] of onUpdateLine.mock.calls) {
      expect(updates).not.toHaveProperty("unit_price");
      expect(updates).not.toHaveProperty("tax_rate");
    }
  });

  it("writes nothing when the suggestion is empty", async () => {
    priceHint.mockResolvedValue({ unit_price: null, tax_rate: null });
    const onUpdateLine = vi.fn();

    await selectTheProduct(onUpdateLine);

    await vi.waitFor(() => {
      expect(onUpdateLine).toHaveBeenCalled();
    });
    for (const [, updates] of onUpdateLine.mock.calls) {
      expect(updates).not.toHaveProperty("unit_price");
      expect(updates).not.toHaveProperty("tax_rate");
    }
  });
});

describe("DocumentLinesEditor — the labels travel with the suggestions", () => {
  it("prints the best-before and the shelf with their labels, end to end", async () => {
    // The editor owns the labels; the row hands them to the dropdown. A
    // test that handed labels straight to the dropdown could not see the
    // editor drop them on the floor — a bare date reads like part of the
    // name, and an unlabelled shelf reads like a typo.
    const user = userEvent.setup();
    searchResults.current = [
      {
        product_template_id: "pt-1",
        item_id: "item-1",
        name: "Yogurt",
        sku: null,
        barcode: null,
        brand: null,
        image_url: null,
        uom_id: null,
        available_quantity: 4,
        expiry_date: "2026-12-01",
        location_name: "Regal — Shelf A",
      },
    ];
    renderEditor({ lines: [emptyLine] });

    await user.click(screen.getAllByRole("combobox")[0]);

    expect(screen.getByText(/expiry date: 2026-12-01/i)).toBeInTheDocument();
    expect(screen.getByText(/location: regal — shelf a/i)).toBeInTheDocument();
    expect(screen.getByText(/in stock: 4/i)).toBeInTheDocument();
  });
});

describe("DocumentLinesEditor — a search limited to the source location", () => {
  const sourceProps = {
    stockLocationId: "dry-goods",
    stockLocationName: "Dry Goods",
  };

  afterEach(() => {
    searchResults.current = [];
    elsewhereResults.current = [];
  });

  it("says the list holds the products in the source location", async () => {
    renderEditor({ ...sourceProps, onChangeSource: vi.fn() });
    await userEvent.click(screen.getByRole("combobox", { name: /item/i }));

    expect(screen.getByText("Products in Dry Goods")).toBeInTheDocument();
  });

  it("points to where a product stands that the source does not hold", async () => {
    // A transfer from Dry Goods, searching for a cheese that stands in Fridge
    // B, used to say "No items found" and nothing more.
    elsewhereResults.current = [
      { name: "Gouda Cheese", location_name: "Fridge B" },
    ];
    const onChangeSource = vi.fn();
    renderEditor({ ...sourceProps, onChangeSource });
    await userEvent.click(screen.getByRole("combobox", { name: /item/i }));

    expect(screen.getByText("Gouda Cheese")).toBeInTheDocument();
    expect(screen.getByText("in Fridge B")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Change source location" }),
    );
    expect(onChangeSource).toHaveBeenCalledTimes(1);
  });

  it("says nothing about a location when the document has none", async () => {
    renderEditor();
    await userEvent.click(screen.getByRole("combobox", { name: /item/i }));

    expect(screen.queryByText(/Products in/)).not.toBeInTheDocument();
  });
});
