import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import type { Item } from "@/types";
import type { StockTakeItem } from "@/modules/stock_takes/types/stock-takes";
import StockTakeItemCard from "./StockTakeItemCard";

function findWithClass(
  container: HTMLElement,
  fragment: string,
): HTMLElement | null {
  return (
    Array.from(container.querySelectorAll<HTMLElement>("*")).find((el) =>
      String(el.className).includes(fragment),
    ) ?? null
  );
}

/**
 * structural guard for CI (vitest runs on every build, the e2e
 * suite measures the real 390 px geometry). The fix moves the counting
 * controls into their own full-width row below the xs breakpoint (475 px)
 * and gives every control a 44 px touch target — these classes are what
 * make the measured layout (save button at x=343 on a 384 px card) hold.
 */
describe("StockTakeItemCard — 390px structural guard", () => {
  it("wraps controls into a full-width row below xs with 44px targets", () => {
    const { container } = render(
      <StockTakeItemCard
        itemId="1"
        item={undefined}
        stockTakeItem={undefined}
        counted=""
        savedCount={null}
        discrepancy={null}
        isSaved={false}
        isUnsaved={false}
        isUpdatePending={false}
        isInProgress={true}
        blindMode={false}
        note=""
        awaitingRecount={false}
        counts={[]}
        onRequestRecount={() => {}}
        reasonCode=""
        reasonNote=""
        showReasonErrors={false}
        onReasonChange={() => {}}
        onNoteChange={() => {}}
        onQuantityChange={() => {}}
        onQuantityStep={() => {}}
        onSave={() => {}}
      />,
    );

    // Header row: stacks below xs, side-by-side from xs up.
    const headerRow = findWithClass(container, "xs:flex-row");
    expect(headerRow).not.toBeNull();
    expect(String(headerRow?.className)).toContain("flex-col");

    // Controls row: full width below xs, auto width from xs up.
    const controls = findWithClass(container, "xs:w-auto");
    expect(controls).not.toBeNull();
    expect(String(controls?.className)).toContain("w-full");

    // Minus / plus / save all get 44 px (h-11) touch targets.
    const buttons = screen.getAllByRole("button");
    expect(buttons.length).toBe(3);
    for (const button of buttons) {
      expect(String(button.className)).toContain("h-11");
    }

    // Quantity field stretches on mobile, fixed w-16 from xs up. The widths
    // sit on the field's box, not on the input inside it — the box is what
    // the row lays out, and an input narrowed inside a full-width box leaves
    // the row unchanged.
    const input = screen.getByRole("textbox", { name: /counted quantity/i });
    expect(String(input.className)).toContain("h-11");

    // input → the `relative` box that positions the icons → the field's box.
    const field = input.closest("div")?.parentElement;
    expect(String(field?.className)).toContain("flex-1");
    expect(String(field?.className)).toContain("xs:flex-none");
    expect(String(field?.className)).toContain("xs:w-16");
  });
});

describe("StockTakeItemCard — two records of one product", () => {
  const card = (expiry: string | null, lot: string | null) => (
    <StockTakeItemCard
      itemId={`bananas-${expiry}`}
      item={
        {
          id: `bananas-${expiry}`,
          name: "Bananas",
          effective_expiry_date: expiry,
        } as unknown as Item
      }
      stockTakeItem={
        {
          item_name: "Bananas",
          shelf_location: "Fridge C",
          lot_name: lot,
        } as unknown as StockTakeItem
      }
      counted=""
      savedCount={null}
      discrepancy={null}
      isSaved={false}
      isUnsaved={false}
      isUpdatePending={false}
      isInProgress={true}
      blindMode={true}
      note=""
      awaitingRecount={false}
      counts={[]}
      onRequestRecount={() => {}}
      reasonCode=""
      reasonNote=""
      showReasonErrors={false}
      onReasonChange={() => {}}
      onNoteChange={() => {}}
      onQuantityChange={() => {}}
      onQuantityStep={() => {}}
      onSave={() => {}}
    />
  );

  it("tells them apart by expiry and batch, on the card and in the field's name", () => {
    // A blind count hides the expected quantity, the one other thing that
    // differed: the two rows read the same, and a counter put every banana
    // on one of them.
    render(
      <>
        {card("2026-10-31", null)}
        {card("2026-10-28", "L-7")}
      </>,
    );

    const fields = screen.getAllByRole("textbox", {
      name: /^Counted quantity of Bananas/,
    });
    const names = fields.map((field) => field.getAttribute("aria-label"));
    expect(new Set(names).size).toBe(2);
    expect(names[0]).toMatch(/expires Oct 31, 2026/);
    expect(names[1]).toMatch(/Batch L-7.*expires Oct 28, 2026/);
    expect(screen.getByText("expires Oct 31, 2026")).toBeVisible();
    expect(screen.getByText("expires Oct 28, 2026")).toBeVisible();
  });
});

describe("StockTakeItemCard — identical records of one product", () => {
  const card = (
    position: number,
    props: {
      discrepancy?: "missing" | null;
      reasonRequired?: boolean;
      note?: string;
    } = {},
  ) => (
    <StockTakeItemCard
      itemId={`cable-${position}`}
      item={
        { id: `cable-${position}`, name: "USB-C Cable 1m" } as unknown as Item
      }
      stockTakeItem={
        {
          item_name: "USB-C Cable 1m",
          shelf_location: "Dock",
        } as unknown as StockTakeItem
      }
      counted=""
      savedCount={null}
      discrepancy={props.discrepancy ?? null}
      twin={{ position, of: 3, added: null }}
      reasonRequired={props.reasonRequired}
      isSaved={false}
      isUnsaved={false}
      isUpdatePending={false}
      isInProgress={true}
      blindMode={true}
      note={props.note ?? ""}
      awaitingRecount={false}
      counts={[]}
      onRequestRecount={() => {}}
      reasonCode=""
      reasonNote=""
      showReasonErrors={false}
      onReasonChange={() => {}}
      onNoteChange={() => {}}
      onQuantityChange={() => {}}
      onQuantityStep={() => {}}
      onSave={() => {}}
    />
  );

  it("numbers the records so their fields do not share a name", () => {
    render(
      <>
        {card(1)}
        {card(2)}
        {card(3)}
      </>,
    );
    const names = screen
      .getAllByRole("textbox", { name: /^Counted quantity of USB-C Cable/ })
      .map((field) => field.getAttribute("aria-label"));
    expect(new Set(names).size).toBe(3);
    expect(names[1]).toMatch(/Record 2 of 3/);
  });

  it("marks the reason required only where completing refuses without it", () => {
    const { rerender } = render(
      card(1, { discrepancy: "missing", reasonRequired: false }),
    );
    expect(screen.getByTestId("discrepancy-reason-code")).not.toBeRequired();
    expect(screen.getByTestId("discrepancy-reason-code")).not.toHaveAttribute(
      "aria-required",
      "true",
    );
    rerender(card(1, { discrepancy: "missing", reasonRequired: true }));
    expect(screen.getByTestId("discrepancy-reason-code")).toHaveAttribute(
      "aria-required",
      "true",
    );
  });

  // A difference carries the reason field with its own note. A second box
  // beside it asked the counter to write the same remark twice.
  it("offers one note field on a line with a difference", () => {
    const { rerender } = render(card(1));
    expect(screen.getAllByPlaceholderText(/note/i)).toHaveLength(1);
    rerender(card(1, { discrepancy: "missing" }));
    expect(screen.queryByPlaceholderText("Add a note…")).toBeNull();
    expect(screen.getByTestId("discrepancy-reason-note")).toBeInTheDocument();
  });

  // A note typed before the Save is on the line when the difference shows up:
  // it stays where the counter can read and change it, not hidden with the box.
  it("keeps a note already on a line with a difference readable and editable", () => {
    render(card(1, { discrepancy: "missing", note: "Dented box" }));
    expect(screen.getByDisplayValue("Dented box")).toBeInTheDocument();
    expect(screen.getByTestId("discrepancy-reason-note")).toBeInTheDocument();
  });

  // Deleting the text of that note must not take the box with it: the box
  // unmounted on the last keystroke and the deletion could never be saved.
  it("keeps the note box of a line with a difference while its saved note is cleared", () => {
    render(
      <StockTakeItemCard
        itemId="cable-1"
        item={undefined}
        stockTakeItem={
          { item_name: "USB-C Cable 1m", notes: "Dented box" } as StockTakeItem
        }
        counted="3"
        savedCount={3}
        discrepancy="missing"
        isSaved={false}
        isUnsaved={true}
        isUpdatePending={false}
        isInProgress={true}
        blindMode={false}
        note=""
        awaitingRecount={false}
        counts={[]}
        onRequestRecount={() => {}}
        reasonCode=""
        reasonNote=""
        showReasonErrors={false}
        onReasonChange={() => {}}
        onNoteChange={() => {}}
        onQuantityChange={() => {}}
        onQuantityStep={() => {}}
        onSave={() => {}}
      />,
    );
    expect(screen.getByPlaceholderText("Add a note…")).toBeInTheDocument();
  });

  // Typed digit by digit, "1.34.13" is no number: the save button stays
  // disabled for it, and the box has to say why.
  it("says so when the counted quantity is not a number", () => {
    const withText = (counted: string) => (
      <StockTakeItemCard
        itemId="cable-1"
        item={undefined}
        stockTakeItem={undefined}
        counted={counted}
        savedCount={null}
        discrepancy={null}
        isSaved={false}
        isUnsaved={false}
        isUpdatePending={false}
        isInProgress={true}
        blindMode={true}
        note=""
        awaitingRecount={false}
        counts={[]}
        onRequestRecount={() => {}}
        reasonCode=""
        reasonNote=""
        showReasonErrors={false}
        onReasonChange={() => {}}
        onNoteChange={() => {}}
        onQuantityChange={() => {}}
        onQuantityStep={() => {}}
        onSave={() => {}}
      />
    );
    const { rerender } = render(withText("1.5"));
    expect(screen.queryByRole("alert")).toBeNull();
    rerender(withText("1.34.13"));
    expect(screen.getByRole("alert")).toHaveTextContent("not a number");
    expect(
      screen.getByRole("textbox", { name: /Counted quantity/ }),
    ).toHaveAttribute("aria-invalid", "true");
  });
  // Nothing is not zero: with an empty box the Save has nothing to record.
  it("keeps Save disabled while the box holds no number", () => {
    const withText = (counted: string) => (
      <StockTakeItemCard
        itemId="cable-1"
        item={undefined}
        stockTakeItem={undefined}
        counted={counted}
        savedCount={null}
        discrepancy={null}
        isSaved={false}
        isUnsaved={true}
        isUpdatePending={false}
        isInProgress={true}
        blindMode={true}
        note=""
        awaitingRecount={false}
        counts={[]}
        onRequestRecount={() => {}}
        reasonCode=""
        reasonNote=""
        showReasonErrors={false}
        onReasonChange={() => {}}
        onNoteChange={() => {}}
        onQuantityChange={() => {}}
        onQuantityStep={() => {}}
        onSave={() => {}}
      />
    );
    const { rerender } = render(withText(""));
    const save = () => screen.getByRole("button", { name: /Save the count/i });
    expect(save()).toBeDisabled();
    rerender(withText("1.34.13"));
    expect(save()).toBeDisabled();
    rerender(withText("0"));
    expect(save()).toBeEnabled();
  });
});
