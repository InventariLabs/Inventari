import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ConsumeDialog } from "./ConsumeDialog";
import type { Item } from "@/types";

// The unit catalogue the precision hooks read. Kilograms count in
// thousandths; an item with no unit falls back to the permissive default.
vi.mock("@/modules/shared/hooks/useUoms", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useFlatUoms: () => ({
    data: [
      {
        id: "uom-kg",
        name: "Kilogram",
        symbol: "kg",
        category_name: "Weight",
        rounding: "0.001000",
      },
    ],
  }),
}));

const item: Item = {
  is_deleted: false,
  id: "item-1",
  location_id: "storage-1",
  category_id: null,
  name: "Olive oil",
  brand: null,
  description: null,
  weight: null,
  quantity: "5",
  added_date: "2026-01-01",
  expiry_date: null,
  freeze_date: null,
  shelf_location: null,
  image_url: null,
  metadata: null,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
};

function renderDialog(onConfirm = vi.fn()) {
  render(
    <ConsumeDialog open item={item} onConfirm={onConfirm} onCancel={vi.fn()} />,
  );
  return onConfirm;
}

async function pickOther(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByRole("combobox"), "OTHER");
}

describe("ConsumeDialog", () => {
  it("asks for nothing extra for a reason that names itself", async () => {
    const onConfirm = renderDialog();
    const user = userEvent.setup();

    expect(screen.queryByTestId("consume-notes")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Remove 1" }));

    expect(onConfirm).toHaveBeenCalledWith(1, "USED", undefined);
  });

  it("asks what it was when the reason is 'Other'", async () => {
    const user = userEvent.setup();
    renderDialog();

    await pickOther(user);

    expect(screen.getByTestId("consume-notes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove 1" })).toBeDisabled();
  });

  it("passes the note along once it is written", async () => {
    const user = userEvent.setup();
    const onConfirm = renderDialog();

    await pickOther(user);
    await user.type(screen.getByTestId("consume-notes"), "spilled");
    await user.click(screen.getByRole("button", { name: "Remove 1" }));

    expect(onConfirm).toHaveBeenCalledWith(1, "OTHER", "spilled");
  });

  it("files the neutral vocabulary, not the food-era one", async () => {
    const user = userEvent.setup();
    const onConfirm = renderDialog();

    // AGENTS.md: USED over CONSUMED, DISPOSED over DISCARDED. The backend
    // still reads the old values on rows that already carry them.
    await user.selectOptions(screen.getByRole("combobox"), "DISPOSED");
    await user.click(screen.getByRole("button", { name: "Remove 1" }));

    expect(onConfirm).toHaveBeenCalledWith(1, "DISPOSED", undefined);
  });

  // The window is modal and focus-trapped through the shared confirm
  // primitive, which exposes it as role="alertdialog" — a modal window role
  // (implicit aria-modal) a screen reader announces, though it does not match
  // a naive [role=dialog] query. This test pins that the dialog
  // never loses its window role.
  it("exposes itself as a modal window", () => {
    renderDialog();

    screen.getByRole("alertdialog");
    expect(
      document.querySelectorAll('[role="dialog"], [role="alertdialog"]'),
    ).toHaveLength(1);
  });

  // Clearing is the first half of every manual entry: select the old value,
  // type the new one. A field that answers the cleared keystroke by restoring
  // its previous number forces the append trick ("12" when 2 was meant), so
  // the empty state has to survive until the next keystroke — the clamp has
  // its place at the commit, not at the typing event.
  it("lets the quantity be cleared before the new number is typed", async () => {
    const user = userEvent.setup();
    const onConfirm = renderDialog();
    const field = screen.getByLabelText("Quantity to remove");

    await user.clear(field);
    expect(field).toHaveValue(null);

    await user.type(field, "2");
    await user.click(screen.getByRole("button", { name: "Remove 2" }));

    expect(onConfirm).toHaveBeenCalledWith(2, "USED", undefined);
  });

  // A cleared field is no amount, and inventing one for it is the same
  // substitution this dialog used to make everywhere: it answered every
  // out-of-range request with 1, so "0,5" left the screen as a whole unit.
  // Nothing is sent until an amount is named.
  it("names no amount while the field is empty, and sends nothing", async () => {
    const user = userEvent.setup();
    const onConfirm = renderDialog();
    const field = screen.getByLabelText("Quantity to remove");

    await user.clear(field);

    const button = screen.getByRole("button", { name: "Remove" });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  // The shelf holds 5. The request used to be trimmed to it at the commit,
  // in silence; now the screen says so and the button stops offering to
  // send it — the reader finds out before the press, not after.
  it("refuses more than the shelf holds, and says so before the press", async () => {
    const user = userEvent.setup();
    const onConfirm = renderDialog();
    const field = screen.getByLabelText("Quantity to remove");

    await user.clear(field);
    await user.type(field, "9");

    expect(screen.getByText(/only 5/i)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Remove 9" });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  // The button names the amount that will leave — the amount that was
  // typed, because nothing is put in its place any more.
  it("names the amount that was typed, not one of its own", async () => {
    const user = userEvent.setup();
    renderDialog();
    const field = screen.getByLabelText("Quantity to remove");

    await user.clear(field);
    await user.type(field, "3");

    expect(
      screen.getByRole("button", { name: "Remove 3" }),
    ).toBeInTheDocument();
  });

  // The unit's word comes from the catalogue like every other word on this
  // screen: the wire writes "pcs", the catalogue writes "pcs.", and the
  // button used to print the wire's spelling.
  it("names the unit the way the catalogue does, not the way the wire writes it", () => {
    render(
      <ConsumeDialog
        open
        item={{
          ...item,
          uom_id: "uom-pcs",
          uom: {
            id: "uom-pcs",
            name: "Piece",
            symbol: "pcs",
            category_name: "Count",
            rounding: "1.000000",
          },
        }}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Remove 1 pcs." }),
    ).toBeInTheDocument();
  });

  // An item counted in kilograms could not give up half of one. The floor
  // was a whole unit for every unit of measure, so 0.5 was raised to 1 and a
  // whole kilogram left the shelf.
  it("lets half a kilogram leave a shelf that counts in kilograms", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <ConsumeDialog
        open
        item={{
          ...item,
          quantity: "6.6",
          uom_id: "uom-kg",
          uom: {
            id: "uom-kg",
            name: "Kilogram",
            symbol: "kg",
            category_name: "Weight",
            rounding: "0.001000",
          },
        }}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    const field = screen.getByLabelText("Quantity to remove");

    await user.clear(field);
    await user.type(field, "0.5");
    await user.click(screen.getByRole("button", { name: /Remove 0[.,]5/ }));

    expect(onConfirm).toHaveBeenCalledWith(0.5, "USED", undefined);
  });
});
