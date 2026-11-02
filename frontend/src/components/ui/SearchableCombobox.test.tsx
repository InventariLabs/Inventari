import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, type Mock } from "vitest";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";

const OPTIONS = [
  { id: "1", name: "Apple", icon: "Apple" },
  { id: "2", name: "Banana" },
  { id: "3", name: "Cherry", icon: "Cherry", color: "#e11d48" },
];

const baseProps = {
  options: OPTIONS,
  value: "",
  onChange: vi.fn(),
};

describe("SearchableCombobox", () => {
  it("renders trigger button with placeholder when no value", () => {
    render(<SearchableCombobox {...baseProps} placeholder="Pick a fruit" />);
    expect(screen.getByText("Pick a fruit")).toBeInTheDocument();
  });

  it("keeps a long placeholder on one line with an ellipsis", () => {
    // A trigger is one line high; a placeholder that wraps spills out of the
    // box in a narrow column. jsdom has no layout, so the classes that do the
    // clipping are what is pinned.
    render(
      <SearchableCombobox
        {...baseProps}
        placeholder="Select partner (optional)"
      />,
    );
    const placeholder = screen.getByText("Select partner (optional)");
    expect(placeholder.className).toContain("truncate");
    expect(placeholder.className).toContain("min-w-0");
  });

  it("associates the label with the trigger and keeps the popover title", () => {
    render(
      <SearchableCombobox {...baseProps} label="Role" title="Select Role" />,
    );
    // The label is wired to the trigger via htmlFor/id, so the button's
    // accessible name matches the visible label (not the popover title).
    expect(screen.getByRole("combobox", { name: "Role" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("combobox", { name: "Role" }));
    // The title prop still renders as the popover header, not the trigger.
    expect(
      screen.getByRole("heading", { name: "Select Role" }),
    ).toBeInTheDocument();
  });

  it("renders selected option name in trigger when value is set", () => {
    render(<SearchableCombobox {...baseProps} value="2" />);
    expect(screen.getByText("Banana")).toBeInTheDocument();
  });

  it("keeps a neutral border and weight when filled (§2.10)", () => {
    render(<SearchableCombobox {...baseProps} value="2" />);
    const trigger = screen.getByRole("combobox");
    // Filled is not a state — a filled combobox reads like a filled Input.
    // Class-by-class, not substring: `focus-visible:border-primary-500` is a
    // focus tint and must survive this assertion.
    const classes = trigger.className.split(/\s+/);
    expect(trigger).toHaveClass("border-border");
    expect(classes).not.toContain("border-primary-500");
    expect(classes).not.toContain("font-medium");
    expect(classes).not.toContain("font-semibold");
  });

  it("opens modal on trigger click", () => {
    render(<SearchableCombobox {...baseProps} title="Choose fruit" />);
    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.getByText("Choose fruit")).toBeInTheDocument();
  });

  it("shows all options when modal opens", () => {
    render(<SearchableCombobox {...baseProps} />);
    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.getByText("Apple")).toBeInTheDocument();
    expect(screen.getByText("Banana")).toBeInTheDocument();
    expect(screen.getByText("Cherry")).toBeInTheDocument();
  });

  it("filters options by search query", () => {
    render(<SearchableCombobox {...baseProps} />);
    fireEvent.click(screen.getByRole("combobox"));
    const searchInput = screen.getByRole("textbox");
    fireEvent.change(searchInput, { target: { value: "ban" } });
    expect(screen.getByText("Banana")).toBeInTheDocument();
    expect(screen.queryByText("Apple")).not.toBeInTheDocument();
    expect(screen.queryByText("Cherry")).not.toBeInTheDocument();
  });

  it("filters options by their path as well as their name", () => {
    render(
      <SearchableCombobox
        {...baseProps}
        options={[
          { id: "1", name: "Shelf A", path: "Cold Storage / Aisle 1" },
          { id: "2", name: "Shelf B", path: "Receiving / Dock" },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("combobox"));
    const searchInput = screen.getByRole("textbox");
    fireEvent.change(searchInput, { target: { value: "receiv" } });
    expect(screen.getByText("Shelf B")).toBeInTheDocument();
    expect(screen.queryByText("Shelf A")).not.toBeInTheDocument();
  });

  it("shows empty message when no options match search", () => {
    render(<SearchableCombobox {...baseProps} emptyMessage="Nothing found" />);
    fireEvent.click(screen.getByRole("combobox"));
    const searchInput = screen.getByRole("textbox");
    fireEvent.change(searchInput, { target: { value: "xyz" } });
    expect(screen.getByText("Nothing found")).toBeInTheDocument();
  });

  it("calls onChange and closes modal on option select", () => {
    const onChange = vi.fn();
    render(<SearchableCombobox {...baseProps} onChange={onChange} />);
    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByText("Banana"));
    expect(onChange).toHaveBeenCalledWith("2");
    // Modal should close — title no longer visible
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("calls onClose callback when closing", () => {
    const onClose = vi.fn();
    render(<SearchableCombobox {...baseProps} onClose={onClose} />);
    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByText("Banana"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes modal on Escape key", () => {
    render(<SearchableCombobox {...baseProps} title="Choose fruit" />);
    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.getByText("Choose fruit")).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByText("Choose fruit")).not.toBeInTheDocument();
  });

  it("closes modal on X button click", () => {
    render(<SearchableCombobox {...baseProps} title="Choose fruit" />);
    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.getByText("Choose fruit")).toBeInTheDocument();
    // The X button is a sibling of the title heading in the header flex row
    const xButton = screen
      .getByText("Choose fruit")
      .parentElement!.querySelector("button")!;
    expect(xButton).not.toBeNull();
    fireEvent.click(xButton);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("clears search when Clear (X) button clicked", () => {
    render(<SearchableCombobox {...baseProps} />);
    fireEvent.click(screen.getByRole("combobox"));
    const searchInput = screen.getByRole("textbox");
    fireEvent.change(searchInput, { target: { value: "app" } });
    expect(searchInput).toHaveValue("app");
    // The clear button is a sibling of the input inside the .relative wrapper
    const clearButton = searchInput.parentElement!.querySelector("button");
    expect(clearButton).not.toBeNull();
    fireEvent.click(clearButton!);
    expect(searchInput).toHaveValue("");
  });

  it("renders custom trigger when passed", () => {
    render(
      <SearchableCombobox
        {...baseProps}
        trigger={<span data-testid="custom-trigger">Custom</span>}
      />,
    );
    expect(screen.getByTestId("custom-trigger")).toBeInTheDocument();
  });

  it("resets search query after closing", () => {
    render(<SearchableCombobox {...baseProps} title="Choose fruit" />);
    fireEvent.click(screen.getByRole("combobox"));
    const searchInput = screen.getByRole("textbox");
    fireEvent.change(searchInput, { target: { value: "ban" } });
    // Close via Escape key
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    // Reopen
    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("shows create button when onCreateNew and createLabel are provided", () => {
    render(
      <SearchableCombobox
        {...baseProps}
        onCreateNew={vi.fn()}
        createLabel="Create new fruit"
      />,
    );
    fireEvent.click(screen.getByRole("combobox"));
    // Empty search: the create button is hidden because there is
    // nothing to interpolate / create.
    expect(screen.queryByText("Create new fruit")).not.toBeInTheDocument();
    const searchInput = screen.getByRole("textbox");
    fireEvent.change(searchInput, { target: { value: "mango" } });
    expect(screen.getByText("Create new fruit")).toBeInTheDocument();
  });

  it("an empty list carries the create door even before anything is typed", () => {
    // An organization with zero partners opens the panel, reads "no
    // partners found" — and used to find nothing but the header close:
    // the create door asked for a typed query first, and nobody types
    // into an empty register. The empty list is itself the reason to
    // offer the way out.
    const onCreateNew = vi.fn();
    render(
      <SearchableCombobox
        {...baseProps}
        options={[]}
        emptyMessage="No partners found"
        onCreateNew={onCreateNew}
        createLabel="Create new partner"
      />,
    );
    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.getByText("No partners found")).toBeInTheDocument();

    const door = screen.getByRole("button", { name: "Create new partner" });
    fireEvent.click(door);
    expect(onCreateNew).toHaveBeenCalledWith("");
  });

  it("hands focus back to the trigger when the create door opens nothing to focus", async () => {
    // A consumer whose handler only sets a value or opens a layer that
    // takes no focus: the panel closes, and focus must not be left on the
    // page body (the next Tab would leave a modal the picker sits in).
    render(
      <SearchableCombobox
        {...baseProps}
        options={[]}
        emptyMessage="No groups found"
        onCreateNew={vi.fn()}
        createLabel="Create new group"
      />,
    );
    const trigger = screen.getByRole("combobox");
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Create new group" }));

    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("offers no create door while the list is still loading", () => {
    // An empty list is not an answer yet: the door it would offer is for a
    // record the list may be about to show.
    const onCreateNew = vi.fn();
    render(
      <SearchableCombobox
        {...baseProps}
        options={[]}
        loading
        emptyMessage="No partners found"
        onCreateNew={onCreateNew}
        createLabel="Create new partner"
      />,
    );
    fireEvent.click(screen.getByRole("combobox"));

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText("No partners found")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Create new partner" }),
    ).toBeNull();
  });

  it("interpolates {{query}} placeholder in createLabel with the typed text", () => {
    render(
      <SearchableCombobox
        {...baseProps}
        onCreateNew={vi.fn()}
        createLabel='Use "{{query}}" as custom role'
      />,
    );
    fireEvent.click(screen.getByRole("combobox"));
    const searchInput = screen.getByRole("textbox");
    fireEvent.change(searchInput, { target: { value: "director" } });
    expect(
      screen.getByText('Use "director" as custom role'),
    ).toBeInTheDocument();
    expect(screen.queryByText("{{query}}")).not.toBeInTheDocument();
  });

  it("calls onCreateNew with search query when create button clicked", () => {
    const onCreateNew = vi.fn();
    render(
      <SearchableCombobox
        {...baseProps}
        onCreateNew={onCreateNew}
        createLabel="Create new"
      />,
    );
    fireEvent.click(screen.getByRole("combobox"));
    const searchInput = screen.getByRole("textbox");
    fireEvent.change(searchInput, { target: { value: "mango" } });
    fireEvent.click(screen.getByText("Create new"));
    expect(onCreateNew).toHaveBeenCalledWith("mango");
  });

  it("does not show create button when onCreateNew is not provided", () => {
    render(<SearchableCombobox {...baseProps} createLabel="Create new" />);
    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.queryByText("Create new")).not.toBeInTheDocument();
  });

  it("does not show create button when createLabel is not provided", () => {
    render(<SearchableCombobox {...baseProps} onCreateNew={vi.fn()} />);
    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.queryByText(/create/i)).not.toBeInTheDocument();
  });
});

/**
 * Where the panel is anchored.
 *
 * A popover anchored to a trigger halfway down a form has around 550px of
 * panel to place and nowhere to put it: Radix flipped it above the trigger
 * and clamped it against the top of the layout viewport, which on a phone is
 * behind the browser chrome. Measured on a 390x620 viewport, the search
 * field sat between -48px and -4px — off-screen, and it is the first thing
 * the reader is meant to type into. Below `sm:` the panel is a bottom sheet
 * (UI_GUIDELINES §4.3), which has no such geometry to get wrong.
 */
describe("SearchableCombobox panel placement", () => {
  const setViewport = (desktop: boolean) => {
    (window.matchMedia as unknown as Mock).mockImplementation(
      (query: string) => ({
        matches: desktop && query.includes("min-width: 640px"),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    );
  };

  // `vi.clearAllMocks()` keeps implementations, so the stub set here would
  // otherwise outlive this block and hand every later test a desktop viewport.
  afterEach(() => setViewport(false));

  it("opens a bottom sheet, not a popover, below `sm:`", () => {
    setViewport(false);
    render(<SearchableCombobox {...baseProps} title="Choose fruit" />);
    fireEvent.click(screen.getByRole("combobox"));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("Choose fruit");
    expect(
      document.querySelector("[data-radix-popper-content-wrapper]"),
    ).toBeNull();
  });

  it("opens the bottom sheet from the caller's own trigger on a phone", () => {
    setViewport(false);
    render(
      <SearchableCombobox
        {...baseProps}
        title="Choose fruit"
        trigger={<span>Pick fruit</span>}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Pick fruit"));

    expect(screen.getByRole("dialog")).toHaveAccessibleName("Choose fruit");
  });

  // Found on screen, not in a spec: the wizard is a fullscreen surface, and
  // the panel opened underneath it — a list of locations whose bottom edge
  // the reader could see and never reach.
  it("joins the tier of the surface it was opened from", () => {
    const tierOf = (props: { layer?: "fullscreen" }) => {
      const view = render(
        <SearchableCombobox
          {...baseProps}
          label="Parent"
          title="Pick a parent"
          {...props}
        />,
      );
      fireEvent.click(screen.getByRole("combobox", { name: "Parent" }));
      let node: HTMLElement | null = screen.getByRole("heading", {
        name: "Pick a parent",
      });
      // The popover carries its tier as a class, the bottom sheet as an
      // inline style — one walk, either way of saying it.
      let tier: string | undefined;
      while (node && !tier) {
        tier =
          /z-\[var\((--z-[a-z-]+)\)\]/.exec(node.className)?.[1] ??
          /var\((--z-[a-z-]+)\)/.exec(node.style.zIndex)?.[1];
        node = node.parentElement;
      }
      view.unmount();
      return tier;
    };

    setViewport(true);
    expect(tierOf({})).toBe("--z-confirm");
    expect(tierOf({ layer: "fullscreen" })).toBe("--z-fullscreen");

    setViewport(false);
    expect(tierOf({})).toBe("--z-modal-nested");
    expect(tierOf({ layer: "fullscreen" })).toBe("--z-fullscreen");
  });

  it("caps the desktop popover at the room Radix measured for it", () => {
    setViewport(true);
    render(<SearchableCombobox {...baseProps} title="Choose fruit" />);
    fireEvent.click(screen.getByRole("combobox"));

    expect(
      document.querySelector("[data-radix-popper-content-wrapper]"),
    ).not.toBeNull();
    // Not `85vh`: on a short window that is still taller than the space the
    // popover has, and the overflow goes off the top of the screen.
    expect(screen.getByRole("dialog").style.maxHeight).toContain(
      "var(--radix-popover-content-available-height)",
    );
  });

  /**
   * `aria-required` has no meaning on a button, and axe reports it there as
   * critical: the requirement was never announced. A combobox carries it —
   * the role Radix gives the trigger of `Select`, the other picker a form
   * row holds.
   */
  it.each([
    ["desktop", true],
    ["phone", false],
  ])("announces a required picker as required on a %s", (_, desktop) => {
    setViewport(desktop);
    render(<SearchableCombobox {...baseProps} label="Storage" required />);

    const trigger = screen.getByRole("combobox", { name: /Storage/ });
    expect(trigger).toHaveAttribute("aria-required", "true");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  /**
   * A combobox names the popup it controls. Radix wires that on the desktop
   * popover; the bottom sheet below `sm:` had no id, so on a phone the
   * trigger pointed nowhere.
   */
  it.each([
    ["desktop", true],
    ["phone", false],
  ])("names the panel it opens on a %s", (_, desktop) => {
    setViewport(desktop);
    render(<SearchableCombobox {...baseProps} title="Choose fruit" />);

    const trigger = screen.getByRole("combobox");
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog");
    expect(dialog.id).not.toBe("");
    expect(trigger).toHaveAttribute("aria-controls", dialog.id);
  });

  /**
   * The popover's trigger props went to a `div` wrapped around a caller's own
   * trigger, so `aria-expanded` sat on an element that may not carry it and
   * the button the reader lands on said nothing about the panel.
   */
  it("puts the popup state on a custom trigger, not on a wrapper", () => {
    setViewport(true);
    render(
      <SearchableCombobox
        {...baseProps}
        title="Choose fruit"
        trigger={<button type="button">Tags</button>}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Tags" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger.parentElement).not.toHaveAttribute("aria-expanded");

    fireEvent.click(trigger);
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Choose fruit");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });
  describe("with a server-side search", () => {
    it("reports the typed query and shows the options as the answer to it", () => {
      const onSearchChange = vi.fn();
      render(
        <SearchableCombobox
          {...baseProps}
          options={[{ id: "9", name: "Zucchini" }]}
          onSearchChange={onSearchChange}
        />,
      );
      fireEvent.click(screen.getByRole("combobox"));
      fireEvent.change(screen.getByRole("textbox"), {
        target: { value: "apple" },
      });

      expect(onSearchChange).toHaveBeenLastCalledWith("apple");
      // The caller's list is not narrowed again by the browser: "Zucchini"
      // does not contain "apple", and is still what the server answered.
      expect(screen.getByText("Zucchini")).toBeInTheDocument();
    });

    it("clears the query for the caller when the panel closes", () => {
      const onSearchChange = vi.fn();
      render(
        <SearchableCombobox {...baseProps} onSearchChange={onSearchChange} />,
      );
      fireEvent.click(screen.getByRole("combobox"));
      fireEvent.change(screen.getByRole("textbox"), {
        target: { value: "ban" },
      });
      fireEvent.click(screen.getByText("Banana"));

      expect(onSearchChange).toHaveBeenLastCalledWith("");
    });

    it("does not pick the first row on Enter while the answer is still on its way", () => {
      const onChange = vi.fn();
      render(
        <SearchableCombobox
          {...baseProps}
          onChange={onChange}
          onSearchChange={vi.fn()}
          loading
        />,
      );
      fireEvent.click(screen.getByRole("combobox"));
      fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });

      expect(onChange).not.toHaveBeenCalled();
    });
  });
});
