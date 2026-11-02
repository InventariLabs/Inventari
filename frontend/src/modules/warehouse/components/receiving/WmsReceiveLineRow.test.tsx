import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "@/test/utils";
import { serveLocations } from "@/test/serveLocations";
import WmsReceiveLineRow from "./WmsReceiveLineRow";
import type { WmsReceiveLine } from "@/modules/warehouse/api/documents_receiving";

const pendingLine: WmsReceiveLine = {
  id: "line-1",
  document_line_id: "doc-line-1",
  from_order: false,
  pick_order: 1,
  status: "pending",
  received_quantity: 0,
  product_name: "Widget",
  lot_name: null,
  expected_quantity: 5,
  uom_symbol: "pcs",
};

describe("WmsReceiveLineRow", () => {
  it("renders a pending line as a plain row, not a fake button", () => {
    const { container } = render(
      <WmsReceiveLineRow
        line={pendingLine}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    const row = container.firstElementChild;
    expect(row).not.toBeNull();
    expect(row).not.toHaveAttribute("role", "button");

    // The real actions inside keep their accessible names.
    expect(
      screen.getByRole("button", { name: "Record received quantity" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Skip line" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Widget")).toBeInTheDocument();
  });

  it("calls a half-received line partially received, not pending", () => {
    // The row showed "2/4 pack" beside a "Pending" badge the moment part of
    // the line had landed — two words for the same line, and the badge was
    // the wrong one.
    render(
      <WmsReceiveLineRow
        line={{ ...pendingLine, received_quantity: 2, expected_quantity: 4 }}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    expect(screen.getByText("Partially received")).toBeInTheDocument();
    expect(screen.queryByText("Pending")).not.toBeInTheDocument();
    // The line is still open: every action a pending line offers stays.
    expect(
      screen.getByRole("button", { name: "Receive full amount" }),
    ).toBeInTheDocument();
  });

  it("offers only undo once the line is resolved", () => {
    render(
      <WmsReceiveLineRow
        line={{ ...pendingLine, status: "short", received_quantity: 2 }}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Record received quantity" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Receive full amount" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Skip line" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("offers undo on a skipped line, which stays on the list", async () => {
    const onUndo = vi.fn();
    render(
      <WmsReceiveLineRow
        line={{ ...pendingLine, status: "skipped" }}
        onUndo={onUndo}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));

    expect(onUndo).toHaveBeenCalledOnce();
  });

  it("names the full receive as its own action", async () => {
    // Every other way out of a line said what it does — "Receive less than
    // expected", "Skip line" — and the one that closes the line in full had
    // no name of its own: it meant typing the expected quantity into the
    // window titled "Record received quantity".
    const onFullReceive = vi.fn();
    render(
      <WmsReceiveLineRow
        line={pendingLine}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={onFullReceive}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Receive full amount" }),
    );
    expect(onFullReceive).toHaveBeenCalledWith(pendingLine);
  });

  it("says how much of a short line went to quarantine, and why", () => {
    // "10/12 pcs. Short" gave no hint that two of the ten were set aside:
    // the held figure was visible only by reopening the quantity window.
    render(
      <WmsReceiveLineRow
        line={{
          ...pendingLine,
          status: "short",
          received_quantity: 10,
          expected_quantity: 12,
          held_quantity: 2,
          discrepancy_code: "DAMAGE",
        }}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    expect(screen.getByText(/^10\/12 pcs/)).toBeInTheDocument();
    expect(
      screen.getByText("2 pcs. in quarantine — Damage"),
    ).toBeInTheDocument();
  });

  it("stays silent about quarantine when nothing was held back", () => {
    render(
      <WmsReceiveLineRow
        line={{
          ...pendingLine,
          status: "short",
          received_quantity: 3,
          held_quantity: 0,
          discrepancy_code: "SHORTAGE",
        }}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    expect(screen.queryByText(/in quarantine/)).not.toBeInTheDocument();
  });

  it("names the shelf even when the plan is the document's own target", () => {
    // The office page suppresses this case because its header already says
    // the target. This screen has no header, so suppressing it here would
    // leave the most ordinary delivery of all with no address on it.
    render(
      <WmsReceiveLineRow
        line={{
          ...pendingLine,
          planned_location_id: "loc-1",
          planned_location_name: "Shelf A - Top",
          planned_source: "document",
        }}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    expect(screen.getByText("→ Shelf A - Top")).toBeInTheDocument();
  });

  it("says which rule chose the shelf, in words rather than an id", () => {
    render(
      <WmsReceiveLineRow
        line={{
          ...pendingLine,
          planned_location_id: "loc-1",
          planned_location_name: "Shelf B",
          planned_source: "rule",
          planned_rule_match_key: "category",
          planned_rule_match_name: "Paints",
        }}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    expect(screen.getByText("rule: category Paints")).toBeInTheDocument();
  });

  it("carries the overflow numbers on their own line, not glued to the shelf", () => {
    // Two short lines instead of one long sentence: at 390px the office
    // page's single sentence wraps into a paragraph and stops being
    // readable at arm's length.
    render(
      <WmsReceiveLineRow
        line={{
          ...pendingLine,
          planned_location_id: "loc-1",
          planned_location_name: "Shelf A - Top",
          planned_source: "rule",
          planned_over_capacity: true,
          planned_capacity_used: "199",
          planned_capacity_max: "200",
        }}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    expect(screen.getByText("→ Shelf A - Top")).toBeInTheDocument();
    expect(
      screen.getByText("full 199/200 — the goods go there anyway"),
    ).toBeInTheDocument();
  });

  it("gives a shared shelf's whole fill instead of one product's pair", () => {
    render(
      <WmsReceiveLineRow
        line={{
          ...pendingLine,
          planned_location_id: "loc-1",
          planned_location_name: "Shelf A - Top",
          planned_source: "rule",
          planned_over_capacity: true,
          planned_capacity_used: "20",
          planned_capacity_max: "40",
          planned_shelf_fill: 110,
        }}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        "location 110% full with every product counted — the goods go there anyway",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/20\/40/)).not.toBeInTheDocument();
  });

  it("reports the shelf the worker picks, and offers none once resolved", async () => {
    serveLocations([{ id: "loc-2", name: "Shelf B - Low" }]);
    const onTargetChange = vi.fn();
    const { rerender } = render(
      <WmsReceiveLineRow
        line={pendingLine}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
        onTargetChange={onTargetChange}
      />,
    );

    // Asserting the combobox renders proves a control exists, not that
    // choosing in it does anything — and a picker wired to nothing looks
    // exactly the same on screen as one that works.
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(
      await screen.findByRole("button", { name: /Shelf B - Low/ }),
    );
    expect(onTargetChange).toHaveBeenCalledWith(pendingLine, "loc-2");

    // The empty option means "follow the plan", and it has to travel as a
    // cleared target rather than as the string the DOM actually holds.
    rerender(
      <WmsReceiveLineRow
        line={pendingLine}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
        targetLocationId="loc-2"
        onTargetChange={onTargetChange}
      />,
    );
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(
      await screen.findByRole("button", { name: /Follow the plan/ }),
    );
    expect(onTargetChange).toHaveBeenLastCalledWith(pendingLine, null);

    rerender(
      <WmsReceiveLineRow
        line={{ ...pendingLine, status: "received" }}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
        onTargetChange={onTargetChange}
      />,
    );
    // The pallet is down; offering to move it would be offering a lie.
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("puts the line's shelf and its planned one at the top of the list, marked", async () => {
    // The list is searched on the server and does not know which row this
    // line is about: the shelf the line names and the one its plan sends the
    // goods to lead it, so the reader hunting for either does not read the
    // whole list to find it.
    serveLocations([
      { id: "loc-3", name: "Overflow", parent_id: "annex" },
      { id: "annex", name: "Annex" },
      { id: "loc-2", name: "Shelf B - Low" },
      { id: "loc-1", name: "Shelf A - Top" },
    ]);
    render(
      <WmsReceiveLineRow
        line={{
          ...pendingLine,
          planned_location_id: "loc-1",
          planned_location_name: "Shelf A - Top",
          planned_source: "rule",
        }}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
        targetLocationId="loc-2"
        onTargetChange={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("combobox"));
    await screen.findByRole("button", { name: /Overflow/ });
    const rows = screen
      .getAllByRole("button")
      .map((button) => button.textContent ?? "")
      .filter((text) => /Shelf|Overflow|Annex/.test(text));
    expect(rows.slice(0, 3)).toEqual([
      expect.stringMatching(/^Shelf B - Low.*current/),
      expect.stringMatching(/^Shelf A - Top.*planned/),
      expect.stringMatching(/^(Annex|Overflow)/),
    ]);
  });

  it("is one row, with the number, the status and the actions beside the name", () => {
    // The picking session lays its line out as one row; this one stacked
    // four lines — name, quantity, an uppercase status, then the actions
    // underneath — for the same facts. Both sessions are worked by the same
    // person with the same phone, often one after the other.
    const { container } = render(
      <WmsReceiveLineRow
        line={pendingLine}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    const row = container.firstElementChild as HTMLElement;
    expect(row).toHaveClass("flex", "items-center");
    // Two children: the text block and the facts-plus-actions block, in the
    // same flex line rather than one under the other.
    expect(row.children).toHaveLength(2);
    const facts = row.lastElementChild as HTMLElement;
    expect(facts).toHaveTextContent("5 pcs");
    expect(facts).toHaveTextContent("Pending");
    expect(
      facts.querySelector('[aria-label="Record received quantity"]'),
    ).not.toBeNull();
    expect(facts.querySelector('[aria-label="Skip line"]')).not.toBeNull();
  });

  it("says how much of a part-received line has already arrived", () => {
    // A short delivery leaves the line pending with part of it counted, and
    // the worker who takes over the session has no way to learn that number
    // from the row: it said only what was ordered. The scan field above and
    // the summary screen below both say "2/5" — the row joins them.
    const { container } = render(
      <WmsReceiveLineRow
        line={{ ...pendingLine, received_quantity: 2 }}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    const facts = container.firstElementChild?.lastElementChild as HTMLElement;
    expect(facts).toHaveTextContent("2/5 pcs");
    expect(facts).not.toHaveTextContent("5 pcsPending");
  });

  it("keeps a line nothing has arrived at as the ordered count alone", () => {
    // "0/5" would be noise on every line of a fresh session: the slash pair
    // is for a count that exists.
    const { container } = render(
      <WmsReceiveLineRow
        line={pendingLine}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

    const facts = container.firstElementChild?.lastElementChild as HTMLElement;
    expect(facts).toHaveTextContent("5 pcs");
    expect(facts).not.toHaveTextContent("0/5");
  });
});

describe("WmsReceiveLineRow's shelf label state", () => {
  const row = (shelfState?: "confirmed" | "toScan" | null) =>
    render(
      <WmsReceiveLineRow
        line={pendingLine}
        shelfState={shelfState}
        onUndo={vi.fn()}
        onShortReceive={vi.fn()}
        onSkip={vi.fn()}
        onFullReceive={vi.fn()}
      />,
    );

  it("says the shelf label is still to be scanned", () => {
    row("toScan");
    expect(
      screen.getByText("Scan the location to confirm"),
    ).toBeInTheDocument();
  });

  it("says the shelf is confirmed", () => {
    row("confirmed");
    expect(screen.getByText("Location confirmed")).toBeInTheDocument();
  });

  it("says nothing when the session does not ask for the label", () => {
    row(null);
    expect(
      screen.queryByText("Scan the location to confirm"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Location confirmed")).not.toBeInTheDocument();
  });
});
