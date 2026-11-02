import { describe, expect, it, vi } from "vitest";

import userEvent from "@testing-library/user-event";
import { render, screen } from "@/test/utils";
import WmsPickLineRow from "./WmsPickLineRow";
import type { WmsPickLine } from "@/modules/warehouse/api/documents";

const pendingLine: WmsPickLine = {
  id: "line-1",
  document_line_id: "doc-line-1",
  pick_order: 1,
  status: "pending",
  picked_quantity: 0,
  product_name: "Widget",
  lot_name: null,
  bin_location: "A-01",
  expected_quantity: 5,
  uom_symbol: "pcs",
};

/**
 * The actions a line offers are icons with no visible label, so their
 * accessible name is the only thing that says what they do — recognition must
 * not depend on where the button sits in the row. The
 * receiving session's row carries the same set.
 */
describe("WmsPickLineRow's action icons", () => {
  it("names all three actions and keeps the 44px target", () => {
    render(
      <WmsPickLineRow
        line={pendingLine}
        onFullPick={vi.fn()}
        onUndo={vi.fn()}
        onShortPick={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

    const fullPick = screen.getByRole("button", {
      name: "Pick full amount",
    });
    const shortPick = screen.getByRole("button", {
      name: "Short pick",
    });
    const skip = screen.getByRole("button", { name: "Skip" });
    for (const button of [fullPick, shortPick, skip]) {
      expect(button).toHaveClass("h-11", "md:h-10");
      expect(button).toHaveAttribute(
        "title",
        button.getAttribute("aria-label"),
      );
    }
  });
});

/**
 * The row itself used to be the way to record a line: it opened the shortfall
 * sheet prefilled with 0, so an ordinary pick was a sheet and a number typed
 * by hand. The receiving row never was a button, and its actions say what
 * they do — so this one is a plain row too, and the full pick is a named
 * action on it.
 */
describe("WmsPickLineRow's row itself", () => {
  it("renders a pending line as a plain row, not a button", () => {
    const { container } = render(
      <WmsPickLineRow
        line={pendingLine}
        onFullPick={vi.fn()}
        onUndo={vi.fn()}
        onShortPick={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

    const row = container.firstElementChild;
    expect(row).not.toBeNull();
    expect(row).not.toHaveAttribute("role", "button");
    expect(row!.tagName).not.toBe("BUTTON");

    // The real actions inside keep their accessible names.
    expect(
      screen.getByRole("button", { name: "Pick full amount" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Short pick" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip" })).toBeInTheDocument();
    expect(screen.getByText("Widget")).toBeInTheDocument();
  });

  it("says how much of a part-picked line is already scanned", () => {
    // A pending line that has been partly scanned showed only the scanned
    // count ("3 pcs.") beside a "Pending" badge, while "Pick full amount"
    // books the document's 10. The receiving row has said "2/5" since a
    // part-received line needed it; this row joins it.
    const { container } = render(
      <WmsPickLineRow
        line={{ ...pendingLine, picked_quantity: 3, expected_quantity: 10 }}
        onFullPick={vi.fn()}
        onUndo={vi.fn()}
        onShortPick={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

    const facts = container.firstElementChild?.lastElementChild as HTMLElement;
    expect(facts).toHaveTextContent("3/10 pcs");
    expect(facts).not.toHaveTextContent("10 pcsPending");
  });

  it("keeps a line nothing has been scanned on as the expected count alone", () => {
    // "0/5" would be noise on every line of a fresh session: the slash pair
    // is for a count that exists.
    const { container } = render(
      <WmsPickLineRow
        line={pendingLine}
        onFullPick={vi.fn()}
        onUndo={vi.fn()}
        onShortPick={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

    const facts = container.firstElementChild?.lastElementChild as HTMLElement;
    expect(facts).toHaveTextContent("5 pcs");
    expect(facts).not.toHaveTextContent("0/5");
  });

  it("records the whole line from the row's Pick full amount action", async () => {
    const onFullPick = vi.fn();
    render(
      <WmsPickLineRow
        line={pendingLine}
        onFullPick={onFullPick}
        onUndo={vi.fn()}
        onShortPick={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Pick full amount" }),
    );

    expect(onFullPick).toHaveBeenCalledWith(pendingLine);
  });

  it("offers the shortfall form only from its own button", async () => {
    const onShortPick = vi.fn();
    render(
      <WmsPickLineRow
        line={pendingLine}
        onFullPick={vi.fn()}
        onUndo={vi.fn()}
        onShortPick={onShortPick}
        onSkip={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText("Widget"));
    expect(onShortPick).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Short pick" }));
    expect(onShortPick).toHaveBeenCalledWith(pendingLine);
  });
});

describe("WmsPickLineRow's text", () => {
  it("says nothing in the row beyond product, bin, amount and status", () => {
    // A `//` written inside JSX children is not a comment: React prints it
    // as text next to the badge, and only the whole row's text shows it.
    const { container } = render(
      <WmsPickLineRow
        line={pendingLine}
        onFullPick={vi.fn()}
        onUndo={vi.fn()}
        onShortPick={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

    expect(container.firstElementChild?.textContent).toBe(
      "WidgetA-015 pcs.Pending",
    );
  });
});

/**
 * At 320px the name shared one row with the quantity, the status badge and
 * three icons and was left 14px. jsdom has no layout, so the wrap is pinned by
 * its classes.
 */
describe("WmsPickLineRow on a narrow sheet", () => {
  it("lets the row wrap and drops the figures under the name", () => {
    render(
      <WmsPickLineRow
        line={pendingLine}
        onFullPick={vi.fn()}
        onUndo={vi.fn()}
        onShortPick={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

    const name = screen.getByText("Widget");
    // The name sits in its own block, which sits in the row's left half.
    const nameBlock = name.parentElement as HTMLElement;
    const nameGroup = nameBlock.parentElement as HTMLElement;
    const row = nameGroup.parentElement as HTMLElement;
    expect(row.className).toContain("flex-wrap");
    expect(nameGroup.className).toContain("basis-40");

    const figures = screen.getByText(/5\s*pcs/).parentElement as HTMLElement;
    expect(figures.className).toContain("ml-auto");
    expect(figures.className).toContain("shrink-0");
  });
});

describe("WmsPickLineRow's shelf label state", () => {
  const row = (shelfState?: "confirmed" | "toScan" | null) =>
    render(
      <WmsPickLineRow
        line={pendingLine}
        shelfState={shelfState}
        onFullPick={vi.fn()}
        onUndo={vi.fn()}
        onShortPick={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

  it("says the shelf label is still to be scanned", () => {
    row("toScan");
    expect(screen.getByText("Scan the location label")).toBeInTheDocument();
  });

  it("says the shelf is confirmed", () => {
    row("confirmed");
    expect(screen.getByText("Location confirmed")).toBeInTheDocument();
  });

  it("says nothing when the session does not ask for the label", () => {
    row(null);
    expect(
      screen.queryByText("Scan the location label"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Location confirmed")).not.toBeInTheDocument();
  });
});

describe("WmsPickLineRow's undo", () => {
  const rowProps = () => ({
    onFullPick: vi.fn(),
    onUndo: vi.fn(),
    onShortPick: vi.fn(),
    onSkip: vi.fn(),
  });

  it("does not undo a picked line by tapping its name", async () => {
    const props = rowProps();
    render(
      <WmsPickLineRow
        line={{ ...pendingLine, status: "picked", picked_quantity: 5 }}
        {...props}
      />,
    );

    await userEvent.click(screen.getByText("Widget"));

    expect(props.onUndo).not.toHaveBeenCalled();
  });

  it.each(["picked", "short", "skipped"] as const)(
    "undoes a %s line through a named Undo button",
    async (status) => {
      const props = rowProps();
      render(<WmsPickLineRow line={{ ...pendingLine, status }} {...props} />);

      await userEvent.click(screen.getByRole("button", { name: "Undo" }));

      expect(props.onUndo).toHaveBeenCalledOnce();
    },
  );

  it("offers no Undo on a line nothing was recorded on", () => {
    render(<WmsPickLineRow line={pendingLine} {...rowProps()} />);

    expect(
      screen.queryByRole("button", { name: "Undo" }),
    ).not.toBeInTheDocument();
  });
});

/**
 * A dated pack with no batch number is stock carrying the date itself; the
 * row says which date the draw reaches first, next to the batch when there is
 * one, and says nothing for stock with no date.
 */
describe("WmsPickLineRow's date", () => {
  const renderRow = (line: WmsPickLine) =>
    render(
      <WmsPickLineRow
        line={line}
        onFullPick={vi.fn()}
        onUndo={vi.fn()}
        onShortPick={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

  it("shows the date of a dated pack that has no batch", () => {
    renderRow({ ...pendingLine, expiry_date: "2026-10-25" });

    expect(screen.getByText("Expires Oct 25, 2026")).toBeInTheDocument();
    expect(screen.queryByText(/^Lot:/)).not.toBeInTheDocument();
  });

  it("shows the date next to the batch", () => {
    renderRow({ ...pendingLine, lot_name: "L-7", expiry_date: "2026-10-25" });

    expect(screen.getByText("Lot: L-7")).toBeInTheDocument();
    expect(screen.getByText("Expires Oct 25, 2026")).toBeInTheDocument();
  });

  it("shows no date for undated stock", () => {
    renderRow({ ...pendingLine, expiry_date: null });

    expect(screen.queryByText(/Expires/)).not.toBeInTheDocument();
  });
});
