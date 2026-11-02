import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PickingItemRow from "./PickingItemRow";
import type { PickingItem } from "@/modules/recipes/types/core";

const baseItem: PickingItem = {
  ingredient_id: "i1",
  name: "Flour",
  quantity_to_pick: 2,
  uom_symbol: "kg",
  recommended_item_id: "item-1",
  location: "Shelf A",
  fefo_days_left: null,
  fefo_expiry_date: null,
  status: "pending",
  is_linked: true,
};

const renderRow = (item: PickingItem, onTap = vi.fn(), onUndo = vi.fn()) =>
  render(<PickingItemRow item={item} onTap={onTap} onUndo={onUndo} />);

describe("PickingItemRow", () => {
  it("picks on tap when the row has a recommended item", () => {
    const onTap = vi.fn();
    renderRow(baseItem, onTap);
    fireEvent.click(screen.getByRole("button"));
    expect(onTap).toHaveBeenCalledWith(baseItem);
  });

  it("stops being a button when nothing can be done to it", () => {
    const onTap = vi.fn();
    const unlinked: PickingItem = {
      ...baseItem,
      recommended_item_id: null,
      is_linked: false,
      status: "unknown",
    };
    renderRow(unlinked, onTap);

    // No role="button" on the row: it carries a link control of its own now,
    // and a control nested in a button is not reachable as its own thing.
    expect(screen.queryByRole("button", { name: /Flour/ })).toBeNull();
    fireEvent.click(screen.getByText("Flour"));
    expect(onTap).not.toHaveBeenCalled();

    expect(screen.getByText("Not linked")).toBeInTheDocument();
  });

  it("says nothing about linking when a linked ingredient ran out", () => {
    renderRow({
      ...baseItem,
      recommended_item_id: null,
      is_linked: true,
      status: "missing",
    });

    expect(screen.queryByText("Not linked")).not.toBeInTheDocument();
  });

  it("keeps an unlinked row pickable when its name found stock", () => {
    const onTap = vi.fn();
    const unlinkedButStocked: PickingItem = { ...baseItem, is_linked: false };
    renderRow(unlinkedButStocked, onTap);

    expect(screen.queryByText("Not linked")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Flour/ }));
    expect(onTap).toHaveBeenCalledWith(unlinkedButStocked);
  });

  it("keeps saying the scan took nothing", () => {
    // The toast carrying this news is gone in seconds, and the checklist is
    // read for as long as the cooking takes. The row used to say "Picked".
    renderRow(baseItem);
    expect(screen.queryByText(/Not taken/)).not.toBeInTheDocument();

    render(
      <PickingItemRow
        item={baseItem}
        refusal="unit_mismatch"
        onTap={vi.fn()}
        onUndo={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Not taken — the units do not match"),
    ).toBeInTheDocument();
  });

  it("activates from the keyboard with Enter and Space", () => {
    const onTap = vi.fn();
    renderRow(baseItem, onTap);
    const row = screen.getByRole("button");
    expect(row.className).toContain("focus-visible:ring-2");

    fireEvent.keyDown(row, { key: "Enter" });
    expect(onTap).toHaveBeenCalledWith(baseItem);

    onTap.mockClear();
    fireEvent.keyDown(row, { key: " " });
    expect(onTap).toHaveBeenCalledWith(baseItem);
  });
});

describe("PickingItemRow — status badge case", () => {
  it("lets the dictionary's case stand on the status badge", () => {
    // CSS `capitalize` rewrote every word of a multi-word label: "Do
    // zebrania" showed as "Do Zebrania", "À sélectionner" worse. The
    // badge renders the translated text exactly as the dictionary wrote
    // it.
    renderRow(baseItem);

    const badge = screen.getByText("To pick");
    expect(badge.className).not.toContain("capitalize");
    expect(badge.textContent).toBe("To pick");
  });

  it("says nothing in the row beyond its name, place, amount and status", () => {
    // A `//` written inside JSX children is not a comment: React prints it
    // as text, a sibling of the badge, and the badge's own node never sees
    // it. Only the whole row's text does.
    renderRow(baseItem);

    expect(screen.getByRole("button").textContent).toBe(
      "FlourShelf A2 kgTo pick",
    );
  });
});
