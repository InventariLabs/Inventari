import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { ProductCombobox, type ProductComboboxOption } from "./ProductCombobox";
import { Sheet } from "./Sheet";

const search = vi.fn<(query: string) => Promise<ProductComboboxOption[]>>();
const onSelect = vi.fn();

function stub(name: string): ProductComboboxOption {
  return {
    product_template_id: `tpl-${name.toLowerCase()}`,
    name,
    sku: null,
    barcode: null,
    image_url: null,
    is_stub: false,
  };
}

const baseProps = {
  value: null,
  onSelect,
  search,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ProductCombobox", () => {
  it("queries the search function once per 250 ms of typing", async () => {
    // Fake timers give the assertion a clock: the debounce must collapse a
    // burst of keystrokes into one query, and the promise resolves inside the
    // fake time.
    vi.useFakeTimers();
    search.mockResolvedValue([stub("Latte cups")]);

    // Type with fireEvent, not userEvent: userEvent's delays respect the fake
    // clock and add their own waits on top of ours.
    render(<ProductCombobox {...baseProps} />);
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "la" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(249);
    });
    expect(search).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2);
    });
    expect(search).toHaveBeenCalledTimes(1);
  });

  it("lets the arrow keys move the highlight and Enter pick", async () => {
    const user = userEvent.setup();
    search.mockResolvedValue([stub("Latte cups"), stub("Cutlery")]);
    render(<ProductCombobox {...baseProps} />);
    const input = screen.getByRole("combobox");

    await user.type(input, "la");
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));

    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute(
      "aria-activedescendant",
      screen.getAllByRole("option")[0].id,
    );
    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute(
      "aria-activedescendant",
      screen.getAllByRole("option")[1].id,
    );
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Cutlery" }),
    );
  });

  it("lets ArrowUp move the highlight back so the reader can correct an overshoot", async () => {
    const user = userEvent.setup();
    search.mockResolvedValue([stub("Latte cups"), stub("Cutlery")]);
    render(<ProductCombobox {...baseProps} />);
    const input = screen.getByRole("combobox");

    await user.type(input, "la");
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}");
    expect(input).toHaveAttribute(
      "aria-activedescendant",
      screen.getAllByRole("option")[0].id,
    );

    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Latte cups" }),
    );
  });

  it("closes the list when the page scrolls under it, but not when the list itself scrolls", async () => {
    const user = userEvent.setup();
    search.mockResolvedValue([stub("Latte cups")]);
    render(<ProductCombobox {...baseProps} />);
    await user.type(screen.getByRole("combobox"), "la");
    const list = await screen.findByRole("listbox");

    fireEvent.scroll(list);
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    fireEvent.scroll(document.body);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("keeps the typed text when the box scrolls its own long text sideways", async () => {
    // A name too long for the box scrolls inside it when the focus comes
    // back — after a refused "add as new", say. That is not the page moving
    // under the list, and it used to wipe the name the reader had to fix.
    const user = userEvent.setup();
    search.mockResolvedValue([stub("Latte cups")]);
    render(<ProductCombobox {...baseProps} />);
    const input = screen.getByRole("combobox");
    await user.type(input, "la");
    await screen.findByRole("listbox");

    fireEvent.scroll(input);

    expect(input).toHaveValue("la");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
  });

  it("prints a chosen SKU but not the random code the server mints", async () => {
    const user = userEvent.setup();
    search.mockResolvedValue([
      { ...stub("Candle wax"), sku: "WAX-01" },
      { ...stub("Wick"), sku: "STM-9240FF63" },
    ]);
    render(<ProductCombobox {...baseProps} />);

    await user.type(screen.getByRole("combobox"), "wa");
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));

    expect(screen.getByText("WAX-01")).toBeInTheDocument();
    expect(screen.queryByText("STM-9240FF63")).not.toBeInTheDocument();
  });

  it("tells same-named products apart once their generated SKUs are hidden", async () => {
    const user = userEvent.setup();
    search.mockResolvedValue([
      {
        ...stub("Soy wax"),
        product_template_id: "tpl-46fb19e8",
        sku: "STM-AC6B673D",
      },
      {
        ...stub("Soy wax"),
        product_template_id: "tpl-43bdfb86",
        sku: "STM-E877A5FD",
        brand: "Second brand",
      },
      { ...stub("Wick"), sku: "STM-9240FF63" },
    ]);
    render(<ProductCombobox {...baseProps} />);

    await user.type(screen.getByRole("combobox"), "so");
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(3));

    const [first, second, wick] = screen.getAllByRole("option");
    expect(first).toHaveTextContent("#fb19e8");
    expect(second).toHaveTextContent("Second brand");
    expect(second).toHaveTextContent("#bdfb86");
    expect(first.textContent).not.toBe(second.textContent);
    // A product nobody else shares the name with stays clean.
    expect(wick).not.toHaveTextContent("#");
  });

  it("closes on Escape and selects nothing", async () => {
    const user = userEvent.setup();
    search.mockResolvedValue([stub("Latte cups")]);
    render(<ProductCombobox {...baseProps} />);

    await user.type(screen.getByRole("combobox"), "la");
    await waitFor(() =>
      expect(screen.getByRole("listbox")).toBeInTheDocument(),
    );

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("draws the list in a portal over the input's viewport position", async () => {
    const user = userEvent.setup();
    search.mockResolvedValue([stub("Latte cups")]);
    render(<ProductCombobox {...baseProps} />);

    await user.type(screen.getByRole("combobox"), "la");
    await waitFor(() =>
      expect(screen.getByRole("listbox")).toBeInTheDocument(),
    );

    const list = screen.getByRole("listbox");
    // Portalled to body, positioned fixed against the input — a modal's
    // overflow-y-auto cannot clip it.
    expect(list.style.position).toBe("fixed");
    expect(list).toHaveStyle({ pointerEvents: "auto" });
    expect(list.ownerDocument.body.contains(list)).toBe(true);
  });

  it("tells assistive tech that a list is open and which row is active", async () => {
    const user = userEvent.setup();
    search.mockResolvedValue([stub("Latte cups")]);
    render(<ProductCombobox {...baseProps} />);

    const input = screen.getByRole("combobox");
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveAttribute("aria-autocomplete", "list");

    await user.type(input, "la");
    await waitFor(() =>
      expect(screen.getByRole("listbox")).toBeInTheDocument(),
    );
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute(
      "aria-controls",
      screen.getByRole("listbox").id,
    );
  });

  it("shows the picked product and calls onClear", async () => {
    const onClear = vi.fn();
    render(
      <ProductCombobox
        {...baseProps}
        value={stub("Latte cups")}
        onClear={onClear}
      />,
    );
    expect(screen.getByText("Latte cups")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(onClear).toHaveBeenCalled();
  });

  it("hands a query with no matches to renderNoResults so the caller can create", async () => {
    const user = userEvent.setup();
    search.mockResolvedValue([]);
    const renderEmpty = vi.fn(() => <div>Nothing found</div>);
    render(<ProductCombobox {...baseProps} renderNoResults={renderEmpty} />);

    await user.type(screen.getByRole("combobox"), "nowy");
    await waitFor(() =>
      expect(screen.getByText("Nothing found")).toBeInTheDocument(),
    );
    expect(renderEmpty).toHaveBeenCalledWith("nowy", expect.any(Function));
  });

  it("says no results found when a finished search matches nothing", async () => {
    const user = userEvent.setup();
    search.mockResolvedValue([]);
    render(<ProductCombobox {...baseProps} />);

    await user.type(screen.getByRole("combobox"), "zz");
    expect(await screen.findByText('No results for "zz"')).toBeInTheDocument();
  });

  it("marks the empty panel as an open suggestion list", async () => {
    // With nothing found the panel carries no listbox role, so the marker is
    // the only thing that tells a surrounding sheet a list is open.
    const user = userEvent.setup();
    search.mockResolvedValue([]);
    render(<ProductCombobox {...baseProps} />);

    await user.type(screen.getByRole("combobox"), "zz");
    await screen.findByText('No results for "zz"');

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(document.querySelector("[data-line-item-dropdown]")).not.toBeNull();
  });

  it("closes the empty panel on the first Escape and the sheet on the next", async () => {
    // The sheet's capture-phase handler runs before the picker's own, so an
    // Escape aimed at the empty panel used to close the sheet, or raise its
    // discard question, while the panel stayed open.
    const user = userEvent.setup();
    const onClose = vi.fn();
    search.mockResolvedValue([]);
    render(
      <Sheet open={true} onClose={onClose}>
        <ProductCombobox {...baseProps} />
      </Sheet>,
    );

    await user.type(screen.getByRole("combobox"), "zz");
    await screen.findByText('No results for "zz"');

    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByText('No results for "zz"')).not.toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps the searching state distinct from an empty result", async () => {
    vi.useFakeTimers();
    let resolveSearch!: (value: ProductComboboxOption[]) => void;
    search.mockImplementation(
      () =>
        new Promise<ProductComboboxOption[]>((resolve) => {
          resolveSearch = resolve;
        }),
    );
    render(<ProductCombobox {...baseProps} />);

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "la" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(251);
    });

    expect(screen.getByText("Searching…")).toBeInTheDocument();
    expect(screen.queryByText(/No results/)).not.toBeInTheDocument();

    await act(async () => {
      resolveSearch([]);
      await Promise.resolve();
    });
    expect(screen.getByText('No results for "la"')).toBeInTheDocument();
    vi.useRealTimers();
  });
});
