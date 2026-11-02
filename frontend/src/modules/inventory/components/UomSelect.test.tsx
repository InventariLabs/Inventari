import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { UomSelect } from "@/modules/shared/components/UomSelect";
import type { Uom, UomCategory } from "@/types";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useUoms: vi.fn(),
}));

import { useUoms } from "@/modules/shared/hooks/useUoms";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const mockUoms: Uom[] = [
  {
    id: "u1",
    name: "gram",
    symbol: "g",
    category_id: "c1",
    factor: "1",
    rounding: "0.001",
    is_reference: true,
    is_system: false,
  },
  {
    id: "u2",
    name: "kilogram",
    symbol: "kg",
    category_id: "c1",
    factor: "1000",
    rounding: "0.001",
    is_reference: false,
    is_system: false,
  },
  {
    id: "u3",
    name: "piece",
    symbol: "pcs",
    category_id: "c2",
    factor: "1",
    rounding: "1",
    is_reference: true,
    is_system: false,
  },
];

const mockCategories: UomCategory[] = [
  { id: "c1", name: "Weight", uoms: [mockUoms[0], mockUoms[1]] },
  { id: "c2", name: "Count", uoms: [mockUoms[2]] },
];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  (useUoms as Mock).mockReturnValue({
    data: mockCategories,
    isLoading: false,
  });
});

// ── Tests ─────────────────────────────────────────────────────────────────────

/** The panel's title — the compact trigger also says "Unit", to readers only. */
const PANEL_TITLE = { selector: ":not(.sr-only)" };

describe("UomSelect", () => {
  it("renders trigger with placeholder when no value selected", () => {
    render(<UomSelect value={null} onChange={vi.fn()} />);
    expect(screen.getByText("Select unit…")).toBeInTheDocument();
  });

  it("says the units did not load and offers a retry when the request failed", () => {
    const refetch = vi.fn();
    (useUoms as Mock).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      refetch,
    });
    render(<UomSelect value={null} onChange={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/error/i);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("shows loading text while uoms are loading", () => {
    (useUoms as Mock).mockReturnValue({
      data: undefined,
      isLoading: true,
    });
    render(<UomSelect value={null} onChange={vi.fn()} />);
    // t() mock returns raw key when no defaultValue is given
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders selected uom name and symbol in trigger", () => {
    render(<UomSelect value="u2" onChange={vi.fn()} />);
    // Non-compact: shows name
    expect(screen.getByText("kilogram")).toBeInTheDocument();
  });

  it("opens the sheet modal on trigger click", () => {
    render(<UomSelect value={null} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));
    // Modal header shows the translated title
    expect(screen.getByText("Unit")).toBeInTheDocument();
  });

  it("calls onChange with correct uom id and object on chip click", () => {
    const onChange = vi.fn();
    render(<UomSelect value={null} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button"));
    // g chip should be visible (COMMON_ORDER includes "g")
    const gChip = screen.getByText("g");
    fireEvent.click(gChip.closest("button")!);
    expect(onChange).toHaveBeenCalledWith("u1", mockUoms[0]);
  });

  it("closes the modal after selection", () => {
    render(<UomSelect value={null} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("Unit")).toBeInTheDocument();
    const gChip = screen.getByText("g");
    fireEvent.click(gChip.closest("button")!);
    expect(screen.queryByText("Unit")).not.toBeInTheDocument();
  });

  it("closes modal on backdrop click", () => {
    render(<UomSelect value={null} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));
    const backdrop = document.querySelector(".absolute.inset-0") as HTMLElement;
    fireEvent.click(backdrop);
    expect(screen.queryByText("Unit")).not.toBeInTheDocument();
  });

  it("closes modal on X button click", () => {
    render(<UomSelect value={null} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("Unit")).toBeInTheDocument();
    // Find the header X button
    // The X button is a sibling of the header title inside the header flex row
    const xButton = screen
      .getByText("Unit")
      .parentElement!.querySelector("button")!;
    expect(xButton).not.toBeNull();
    fireEvent.click(xButton);
    expect(screen.queryByText("Unit")).not.toBeInTheDocument();
  });

  it("shows error message when error prop provided", () => {
    render(
      <UomSelect value={null} onChange={vi.fn()} error="Unit is required" />,
    );
    expect(screen.getByText("Unit is required")).toBeInTheDocument();
  });

  it("renders as disabled trigger when disabled prop is true", () => {
    render(<UomSelect value={null} onChange={vi.fn()} disabled />);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("renders compact mode trigger with symbol only", () => {
    render(<UomSelect value="u1" onChange={vi.fn()} compact />);
    // Compact shows symbol inline; full name not shown in trigger
    const btn = screen.getByRole("button");
    expect(btn.textContent).toContain("g");
    expect(btn.textContent).not.toContain("gram");
  });

  it.each([
    ["compact", true],
    ["full", false],
  ])(
    "keeps the %s trigger on the one border weight every control uses",
    (_name, compact) => {
      // UI_GUIDELINES §2.10: a 2px border made the unit picker draw a heavier
      // box than the quantity and price fields on the same document line.
      render(<UomSelect value="u1" onChange={vi.fn()} compact={compact} />);
      expect(screen.getByRole("button").className.split(/\s+/)).not.toContain(
        "border-2",
      );
    },
  );

  it("saves to localStorage on selection (recent uoms)", () => {
    render(<UomSelect value={null} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));
    const gChip = screen.getByText("g");
    fireEvent.click(gChip.closest("button")!);
    const stored = JSON.parse(
      localStorage.getItem("inventari:recentUomIds") ?? "[]",
    );
    expect(stored).toContain("u1");
  });

  it("opens an inline popover (not a modal) when inline prop is set", () => {
    const onChange = vi.fn();
    render(<UomSelect inline compact value={null} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button"));
    // Panel title visible; popover has no modal backdrop (bg-black/50 sheet)
    expect(screen.getByText("Unit", PANEL_TITLE)).toBeInTheDocument();
    expect(document.querySelector('[class*="bg-black/50"]')).toBeNull();
    const gChip = screen.getByText("g");
    fireEvent.click(gChip.closest("button")!);
    expect(onChange).toHaveBeenCalledWith("u1", mockUoms[0]);
    // Panel closes after selection
    expect(screen.queryByText("Unit", PANEL_TITLE)).not.toBeInTheDocument();
  });

  it("renders the inline panel through a portal, escaping clipping ancestors", () => {
    const { container } = render(
      <div className="overflow-hidden">
        <UomSelect inline compact value={null} onChange={vi.fn()} />
      </div>,
    );
    const clipped = container.firstElementChild!;
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("Unit", PANEL_TITLE)).toBeInTheDocument();
    // Before the fix the panel was absolutely positioned inside the trigger's
    // relative wrapper and got clipped by the overflow-hidden card — clicks
    // landed on the fixed backdrop and the panel closed instantly, so "pcs"
    // was unreachable. The panel must render in a portal, outside the card.
    expect(clipped).not.toContainElement(screen.getByText("Unit", PANEL_TITLE));
  });

  it("offers only units convertible into the one given, and says why", () => {
    // A recipe line whose quantity the maker converts into the ingredient's
    // stock unit: pieces can never be read as grams, so offering them is
    // offering the refusal the guard will answer with.
    render(
      <UomSelect
        value={null}
        onChange={vi.fn()}
        convertibleTo="u1"
        convertibleHint="Only units convertible into g are offered."
      />,
    );
    fireEvent.click(screen.getByRole("button"));

    expect(screen.getByText("kg")).toBeInTheDocument();
    expect(screen.queryByText("pcs.")).not.toBeInTheDocument();
    expect(
      screen.getByText("Only units convertible into g are offered."),
    ).toBeInTheDocument();
  });

  it("widens the list to the categories of every unit given", () => {
    // A product kept in pieces whose card states a weight per piece: the
    // piece itself and the weight's units can all be read as the stock unit.
    render(
      <UomSelect
        value={null}
        onChange={vi.fn()}
        convertibleTo={["u3", "u1"]}
      />,
    );
    fireEvent.click(screen.getByRole("button"));

    expect(screen.getByText("kg")).toBeInTheDocument();
    expect(screen.getByText("pcs.")).toBeInTheDocument();
  });

  it("offers every unit when no convertible one is named", () => {
    render(<UomSelect value={null} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));

    expect(screen.getByText("kg")).toBeInTheDocument();
    expect(screen.getByText("pcs.")).toBeInTheDocument();
  });

  it("shows More options toggle and expands rare uoms", () => {
    render(<UomSelect value={null} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));
    // "More options" button should be present
    const moreBtn = screen.getByText("More options");
    expect(moreBtn).toBeInTheDocument();
    fireEvent.click(moreBtn);
    expect(screen.getByText("Less options")).toBeInTheDocument();
  });
});
