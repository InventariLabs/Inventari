import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { LineItemRow } from "./LineItemRow";
import type { LineItem, LineItemProduct, LineItemsEditorLabels } from "./types";

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
  adHocBadge: "Ad-hoc",
  adHocBadgeTooltip: "Free-text line, not linked to a product",
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

const makeLine = (overrides: Partial<LineItem> = {}): LineItem => ({
  key: "k1",
  name: "Piwo Tyskie",
  sku: "WH-00702",
  barcode: "5901234567890",
  brand: "Tyskie",
  quantity: 6,
  uom_id: "uom-pcs",
  ...overrides,
});

const makeProps = () => ({
  index: 0,
  mode: "document" as const,
  features: {},
  labels: makeLabels(),
  search: {
    results: [] as LineItemProduct[],
    isLoading: false,
    onQuery: vi.fn(),
    onClear: vi.fn(),
  },
  renderUomSelect: () => null,
  gridClass: "xl:grid-cols-[minmax(0,1fr)_110px_100px_40px_20px]",
  isOptionalExpanded: false,
  dateLang: "en",
  onToggleOptional: vi.fn(),
  onUpdate: vi.fn(),
  onRemove: vi.fn(),
  onSelectProduct: vi.fn(),
  rowTestId: "document-line-card-layout-0",
  optionalPanelTestId: "document-line-optional-panel-0",
});

describe("LineItemRow — collapsed", () => {
  it("shows SKU, barcode, name and brand for a linked product", () => {
    const props = makeProps();
    render(<LineItemRow {...props} line={makeLine({ item_id: "item-1" })} />);
    expect(screen.getByText(/WH-00702/)).toBeInTheDocument();
    expect(screen.getByText(/5901234567890/)).toBeInTheDocument();
    expect(screen.getByText(/Piwo Tyskie/)).toBeInTheDocument();
    expect(screen.getAllByText(/Tyskie/).length).toBeGreaterThanOrEqual(1);
  });

  it("shows name input when no product is linked (free-text line)", () => {
    const props = makeProps();
    render(
      <LineItemRow
        {...props}
        line={makeLine({ sku: undefined, barcode: undefined })}
      />,
    );
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("names the product input after its label, not just its placeholder", () => {
    // A placeholder disappears on the first keystroke; the product field is
    // how a free-text line says what it is, so it carries its own name.
    const props = makeProps();
    render(
      <LineItemRow
        {...props}
        line={makeLine({ sku: undefined, barcode: undefined })}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Item" })).toBeInTheDocument();
  });

  it("renders the ad-hoc badge on a free-text line (no item_id or product_template_id)", () => {
    const props = makeProps();
    render(
      <LineItemRow
        {...props}
        line={makeLine({ sku: undefined, barcode: undefined })}
      />,
    );
    expect(screen.getByTestId("line-item-adhoc-badge-0")).toBeInTheDocument();
    expect(screen.getByTestId("line-item-adhoc-badge-0")).toHaveTextContent(
      "Ad-hoc",
    );
  });

  it("does NOT render the ad-hoc badge when a product is linked", () => {
    const props = makeProps();
    render(
      <LineItemRow
        {...props}
        line={makeLine({ item_id: "item-1", product_template_id: "pt-1" })}
      />,
    );
    expect(
      screen.queryByTestId("line-item-adhoc-badge-0"),
    ).not.toBeInTheDocument();
  });

  it("keeps free-text name editable and reports keystrokes", async () => {
    const props = makeProps();
    const user = userEvent.setup();
    const { rerender } = render(
      <LineItemRow {...props} line={makeLine({ name: "" })} />,
    );
    await user.type(screen.getByRole("combobox"), "W");
    expect(props.onUpdate).toHaveBeenCalledWith({ name: "W" });
    rerender(<LineItemRow {...props} line={makeLine({ name: "W" })} />);
    await user.type(screen.getByRole("combobox"), "i");
    expect(props.onUpdate).toHaveBeenCalledWith({ name: "Wi" });
    expect(props.search.onQuery).toHaveBeenCalledWith("Wi");
  });

  it("shows quantity input with the line quantity", () => {
    const props = makeProps();
    render(<LineItemRow {...props} line={makeLine()} />);
    expect(screen.getByDisplayValue("6")).toBeInTheDocument();
  });

  it("keeps a fraction typed character by character — the dot step reports empty, not zero", () => {
    // While "12.5" is typed into a number field, the browser
    // reports "1", "12", "" (the incomplete "12."), "12.5" — one change
    // event per keystroke. The row used to answer the "" with
    // Number("") === 0, the controlled field rewrote itself to "0", and the
    // dot the reader was still holding died with it: the line ended with
    // quantity 5 and a field reading "05".
    const props = makeProps();
    render(<LineItemRow {...props} line={makeLine({ quantity: 12 })} />);
    const field = screen.getByRole("spinbutton", { name: "Quantity" });

    fireEvent.change(field, { target: { value: "1" } });
    fireEvent.change(field, { target: { value: "12" } });
    expect(props.onUpdate).toHaveBeenCalledWith({ quantity: 12 });

    fireEvent.change(field, { target: { value: "" } });
    expect(field).toHaveValue(null);
    expect(props.onUpdate).not.toHaveBeenCalledWith({ quantity: 0 });

    fireEvent.change(field, { target: { value: "12.5" } });
    expect(props.onUpdate).toHaveBeenCalledWith({ quantity: 12.5 });
    expect(field).toHaveValue(12.5);
  });

  it("does NOT show unit price when valueFields is off", () => {
    const props = makeProps();
    render(<LineItemRow {...props} line={makeLine()} />);
    expect(screen.queryByText(/Unit Price/i)).not.toBeInTheDocument();
  });

  it("shows unit price when valueFields is on", () => {
    const props = makeProps();
    render(
      <LineItemRow
        {...props}
        features={{ valueFields: true }}
        line={makeLine({ unit_price: "18.50" })}
      />,
    );
    expect(screen.getAllByText(/Unit Price/i)[0]).toBeInTheDocument();
  });

  it("calls onRemove from the delete button", async () => {
    const props = makeProps();
    const user = userEvent.setup();
    render(<LineItemRow {...props} line={makeLine()} />);
    await user.click(
      screen.getAllByRole("button", { name: /remove line/i })[0],
    );
    expect(props.onRemove).toHaveBeenCalledOnce();
  });
});

describe("LineItemRow — product search", () => {
  const results: LineItemProduct[] = [
    {
      product_template_id: "pt-1",
      name: "Existing Widget",
      sku: "SKU-1",
      barcode: "123456",
      brand: "ACME",
      image_url: null,
      uom_id: null,
    },
    {
      product_template_id: "pt-2",
      name: "Other Widget",
      sku: null,
      barcode: null,
      brand: null,
      image_url: null,
      uom_id: null,
    },
  ];

  it("selects a product via mouse click", async () => {
    const props = makeProps();
    props.search.results = results;
    const user = userEvent.setup();
    render(<LineItemRow {...props} line={makeLine({ name: "Wid" })} />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    await user.click(screen.getByText("Existing Widget"));
    expect(props.onSelectProduct).toHaveBeenCalledWith(results[0]);
    expect(props.search.onClear).toHaveBeenCalled();
  });

  it("selects a product via keyboard navigation (ArrowDown + Enter)", async () => {
    const props = makeProps();
    props.search.results = results;
    const user = userEvent.setup();
    render(<LineItemRow {...props} line={makeLine({ name: "Wid" })} />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    await user.keyboard("{ArrowDown}{Enter}");
    expect(props.onSelectProduct).toHaveBeenCalledWith(results[1]);
  });

  it("takes the first match on Enter when the arrows were not used", async () => {
    const props = makeProps();
    props.search.results = results;
    const user = userEvent.setup();
    render(<LineItemRow {...props} line={makeLine({ name: "Wid" })} />);
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("{Enter}");
    expect(props.onSelectProduct).toHaveBeenCalledWith(results[0]);
  });

  it("clears the search on Escape", async () => {
    const props = makeProps();
    props.search.results = results;
    const user = userEvent.setup();
    render(<LineItemRow {...props} line={makeLine({ name: "Wid" })} />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    await user.keyboard("{Escape}");
    expect(props.search.onClear).toHaveBeenCalled();
  });

  it("closes the no-results panel on Escape instead of leaving the press to the sheet", async () => {
    // With nothing found, the panel holds no listbox and the input's handler
    // returned early: the press travelled to the sheet, which asked its
    // discard question while the panel stayed open.
    const props = makeProps();
    const user = userEvent.setup();
    render(<LineItemRow {...props} line={makeLine({ name: "zzzz" })} />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    expect(screen.getByText("No results found")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByText("No results found")).not.toBeInTheDocument();
    expect(props.search.onClear).toHaveBeenCalled();
  });

  it("closes the results panel rather than swapping in the empty one", async () => {
    // Escape used to clear the results, and the panel — still open — redrew
    // as "No results found". The first press belongs to the panel, and the
    // panel is what it closes.
    const props = makeProps();
    props.search.results = results;
    const user = userEvent.setup();
    render(<LineItemRow {...props} line={makeLine({ name: "Wid" })} />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    expect(screen.getByText("Existing Widget")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByText("Existing Widget")).not.toBeInTheDocument();
    expect(screen.queryByText("No results found")).not.toBeInTheDocument();
  });

  it("reopens the picker when typing resumes after Escape", async () => {
    // Escape dismisses the panel while the input keeps the focus, and an
    // input that never lost it gets no second focus event: typing itself has
    // to bring the panel back.
    const props = makeProps();
    const user = userEvent.setup();
    const { rerender } = render(
      <LineItemRow {...props} line={makeLine({ name: "zz" })} />,
    );
    const input = screen.getByRole("combobox");
    await user.click(input);
    await user.keyboard("{Escape}");
    expect(screen.queryByText("No results found")).not.toBeInTheDocument();

    await user.type(input, "z");
    rerender(<LineItemRow {...props} line={makeLine({ name: "zzz" })} />);

    expect(screen.getByText("No results found")).toBeInTheDocument();
  });

  it("clears product link and metadata when the clear button is clicked", async () => {
    const props = makeProps();
    const user = userEvent.setup();
    render(
      <LineItemRow
        {...props}
        line={makeLine({ item_id: "item-1", product_template_id: "pt-1" })}
      />,
    );
    await user.click(screen.getByRole("button", { name: /clear/i }));
    expect(props.onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        item_id: null,
        product_template_id: null,
        sku: null,
        barcode: null,
        brand: null,
        image_url: null,
      }),
    );
  });
});

describe("LineItemRow — optional fields", () => {
  it("hides the optional panel when not expanded", () => {
    const props = makeProps();
    render(<LineItemRow {...props} line={makeLine()} />);
    expect(
      screen.queryByTestId("document-line-optional-panel-0"),
    ).not.toBeInTheDocument();
  });

  it("shows batch, serial and notes when expanded", () => {
    const props = makeProps();
    render(
      <LineItemRow
        {...props}
        isOptionalExpanded={true}
        features={{ optionalFields: true }}
        line={makeLine()}
      />,
    );
    expect(
      screen.getByTestId("document-line-optional-panel-0"),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Batch Number/i)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/Serial Number/i)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/Notes/i)[0]).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add Expiry Date" }),
    ).toBeInTheDocument();
  });

  it("uses the desktop grid class passed from the editor", () => {
    const props = makeProps();
    render(<LineItemRow {...props} line={makeLine()} />);
    expect(screen.getByTestId("document-line-card-layout-0")).toHaveClass(
      "xl:grid",
      "xl:grid-cols-[minmax(0,1fr)_110px_100px_40px_20px]",
    );
  });
});

describe("LineItemRow suggestion semantics", () => {
  it("announces the suggestion list and the highlighted entry", async () => {
    // The list rendered and the arrow keys moved through it, but a screen
    // reader was never told it existed, let alone which row was current.
    const user = userEvent.setup();
    const product = (id: string, name: string): LineItemProduct => ({
      product_template_id: id,
      name,
      sku: null,
      barcode: null,
      brand: null,
      uom_id: null,
      image_url: null,
    });
    render(
      <LineItemRow
        {...makeProps()}
        line={makeLine({ name: "MacBook" })}
        search={{
          results: [
            product("pt-1", "MacBook Pro"),
            product("pt-2", "MacBook Air"),
          ],
          isLoading: false,
          onQuery: vi.fn(),
          onClear: vi.fn(),
        }}
      />,
    );

    const input = screen.getByRole("combobox");
    expect(input).toHaveAttribute("aria-autocomplete", "list");

    await user.click(input);
    expect(input).toHaveAttribute("aria-expanded", "true");

    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(2);
    expect(input).toHaveAttribute(
      "aria-controls",
      screen.getByRole("listbox").id,
    );

    // The first match is highlighted before any key is pressed.
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);
    expect(options[0]).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant", options[1].id);
    expect(options[1]).toHaveAttribute("aria-selected", "true");
  });
});

describe("LineItemRow — the labels travel with the suggestions", () => {
  it("prints the best-before and the shelf with their labels, not bare", async () => {
    // The row is the component that owns the labels, and the dropdown only
    // knows what it is handed. A test passing labels straight to the
    // dropdown could not see the row drop them on the floor — a date
    // rendered bare, indistinguishable from a number typed into the name.
    const user = userEvent.setup();
    const props = makeProps();
    props.labels = {
      ...props.labels,
      inStock: "In stock",
      expiryLabel: "Expiry date",
      storageLabel: "Location",
    };
    props.search.results = [
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

    render(<LineItemRow {...props} line={makeLine({ name: "Yog" })} />);
    await user.click(screen.getByRole("combobox"));

    expect(screen.getByText(/expiry date: 2026-12-01/i)).toBeInTheDocument();
    expect(screen.getByText(/location: regal — shelf a/i)).toBeInTheDocument();
    expect(screen.getByText(/in stock: 4/i)).toBeInTheDocument();
  });
});

describe("LineItemRow — the blur grace timer", () => {
  it("takes the timer back when the row goes away inside the window", () => {
    // The 200 ms blur grace exists so a click on a dropdown option lands
    // before the list closes. Scheduled from an event handler, nobody owned
    // its id: a row removed inside the window fired its state set on a dead
    // component, and vitest reported an unhandled error after teardown —
    // green tests, exit 1.
    const setTimeoutSpy = vi.spyOn(window, "setTimeout");
    const clearTimeoutSpy = vi.spyOn(window, "clearTimeout");
    const props = makeProps();
    const { unmount } = render(
      <LineItemRow
        {...props}
        line={makeLine({ sku: undefined, barcode: undefined })}
      />,
    );

    const name = screen.getByRole("combobox");
    // Called the way the browser would call it — through the handler React
    // binds to the element. The synthetic focusin/focusout dance is jsdom
    // theatre: the contract under test is what onBlur schedules and what
    // unmount takes back.
    const reactPropsKey = Object.keys(name).find((k) =>
      k.startsWith("__reactProps"),
    ) as keyof HTMLElement;
    (name[reactPropsKey] as { onBlur?: () => void }).onBlur?.();

    // Under vitest's jsdom environment a scheduled timer comes back as a
    // Node Timeout object, not a numeric id — compare the handles the spy
    // handed out with the ones clearTimeout received, not their types.
    const scheduled = setTimeoutSpy.mock.results.map((entry) => entry.value);
    expect(scheduled.length).toBeGreaterThan(0);

    unmount();

    const cleared = clearTimeoutSpy.mock.calls.flat();
    for (const id of scheduled) {
      expect(cleared, "a timer outlived the row").toContain(id);
    }
  });
});

describe("LineItemRow — a line that opens with a typed name", () => {
  // A saved draft or a pasted list opens with names nobody has searched for
  // yet. The panel used to answer "No results found" on focus, and on a
  // receipt offer to make a product of a name the list may already hold.
  it("searches for its name when it gets the focus", async () => {
    const props = makeProps();
    const createNew = {
      label: (name: string) => `Add ${name}`,
      onCreate: vi.fn(),
    };
    render(
      <LineItemRow
        {...props}
        search={{ ...props.search, createNew }}
        line={makeLine({ name: "Widget", sku: undefined, barcode: undefined })}
      />,
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Item" }));

    expect(props.search.onQuery).toHaveBeenCalledWith("Widget");
  });

  it("hands the typed name and its line to the offer", async () => {
    const props = makeProps();
    const onCreate = vi.fn();
    render(
      <LineItemRow
        {...props}
        search={{
          ...props.search,
          createNew: { label: (name) => `Add ${name}`, onCreate },
        }}
        line={makeLine({ name: "Widget ", sku: undefined, barcode: undefined })}
      />,
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Item" }));
    await userEvent.click(screen.getByRole("button", { name: "Add Widget" }));

    expect(onCreate).toHaveBeenCalledWith("k1", "Widget");
  });
});
