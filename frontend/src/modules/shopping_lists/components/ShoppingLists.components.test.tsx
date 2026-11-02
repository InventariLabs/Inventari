import { describe, it, expect, vi } from "vitest";
import { withLanguage } from "@/test/mocks/i18n";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { signInWith } from "@/test/auth";
import { ShoppingListCard } from "./ShoppingListCard";
import CreateShoppingListModal from "./CreateShoppingListModal";
import AddToShoppingListButton from "./AddToShoppingListButton";
import type { Item } from "@/types";
import type { ShoppingList } from "@/modules/shopping_lists/types/shopping";

vi.mock("@/modules/shopping_lists/api/shopping-lists", () => ({
  shoppingListsApi: {
    create: vi.fn().mockResolvedValue({ id: "new-1", name: "Test List" }),
  },
}));

vi.mock("@/modules/shopping_lists/hooks/useShoppingLists", () => ({
  useQuickAddToShoppingList: vi.fn(() => ({
    mutate: vi.fn(),
    isPending: false,
  })),
}));

const noop = vi.fn();

const makeList = (overrides: Partial<ShoppingList> = {}): ShoppingList => ({
  id: "list-1",
  organization_id: "org-1",
  name: "Weekly Shopping",
  status: "active",
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

const makeItem = (): Item => ({
  is_deleted: false,
  id: "item-1",
  location_id: "loc-1",
  category_id: null,
  name: "Milk",
  brand: null,
  description: null,
  weight: null,
  uom_id: null,
  uom: null,
  quantity: "2",
  added_date: "2026-01-01",
  expiry_date: null,
  freeze_date: null,
  shelf_location: null,
  image_url: null,
  metadata: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

// ─── ShoppingListCard ─────────────────────────────────────────────────────────

describe("ShoppingListCard", () => {
  const defaultProps = {
    list: makeList(),
    stats: {
      total: 10,
      purchased: 4,
      names: ["Flour", "Sugar", "Butter"],
    },
    editingName: null as string | null,
    newName: "",
    onSetNewName: noop,
    onStartEditName: noop,
    onSaveName: noop,
    to: "/shopping-lists/list-1",
    onDeleteRequest: noop,
  };

  const renderCard = (props: Partial<typeof defaultProps> = {}) =>
    render(
      <MemoryRouter>
        <ShoppingListCard {...defaultProps} {...props} />
      </MemoryRouter>,
    );

  it("renders the list name", () => {
    renderCard();
    expect(screen.getByText("Weekly Shopping")).toBeInTheDocument();
  });

  it("renders purchased / total badge", () => {
    renderCard();
    expect(screen.getByText(/4.*\/.*10/)).toBeInTheDocument();
  });

  /**
   * The figure beside the bar was `Math.round`'s own answer with a percent
   * sign typed after it — no formatter, so no language. French typography
   * keeps a space before the sign and the label said "33%".
   */
  it("writes the progress percentage the way the language writes one", async () => {
    await withLanguage("fr", () => {
      renderCard({ stats: { total: 3, purchased: 1, names: ["Flour"] } });

      expect(screen.getByText(/33\s%/)).toBeInTheDocument();
      expect(screen.queryByText(/33%/)).not.toBeInTheDocument();
    });
  });

  /**
   * The preview used to be four identical box glyphs in a stack of
   * overlapping circles: nothing that told one list from another, and the
   * shape of an avatar stack, which says the circles are people. The names
   * were in the same answer the counts came from.
   */
  it("previews what is on the list, and how much more there is", () => {
    renderCard();

    expect(screen.getByText(/Flour, Sugar, Butter/)).toBeInTheDocument();
    expect(screen.getByText("and 7 more")).toBeInTheDocument();
  });

  it("says so when the list is empty rather than drawing nothing", () => {
    renderCard({ stats: { total: 0, purchased: 0, names: [] } });

    expect(screen.getByText("Nothing on this list yet")).toBeInTheDocument();
  });

  /**
   * The card used to navigate from a `<div onClick>` covering its top half:
   * no role, no focus, nothing for a screen reader, and hover feedback on a
   * surface that answered a click on only part of itself. The title is the
   * link now, stretched over the card.
   */
  it("navigates from a real link on the title", () => {
    renderCard();

    const title = screen.getByRole("link", { name: "Weekly Shopping" });
    expect(title).toHaveAttribute("href", "/shopping-lists/list-1");
  });

  it("announces the destination once, not twice", () => {
    renderCard();

    // The visible "Open" button leads to the same place and is hidden from
    // assistive technology for that reason.
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });

  it("keeps the row actions reachable above the overlay", () => {
    renderCard();

    const menu = screen.getByRole("button", {
      name: /actions for weekly shopping/i,
    });
    expect(menu.closest(".z-10")).not.toBeNull();
  });

  /**
   * Renaming and deleting act on the record, not on what the reader is doing
   * right now, so they live behind the "⋯" — the same place the recipe detail
   * keeps deleting. The bin used to sit bare on the card, one pixel from the
   * rename pencil.
   */
  it("keeps the record's actions behind the overflow menu", async () => {
    const onDeleteRequest = vi.fn();
    renderCard({ onDeleteRequest });

    expect(screen.queryByLabelText(/delete list/i)).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /actions for weekly shopping/i }),
    );
    fireEvent.click(await screen.findByText("Delete list"));

    expect(onDeleteRequest).toHaveBeenCalled();
  });

  it("shows 'Done' badge when all items purchased", () => {
    renderCard({ stats: { total: 5, purchased: 5, names: ["Flour"] } });
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("renders editing input when editingName matches list id", () => {
    renderCard({ editingName: "list-1", newName: "New Name" });
    const input = screen.getByRole("textbox");
    expect(input).toHaveValue("New Name");
  });

  it("does not stretch a link over the card while the name is being edited", () => {
    renderCard({ editingName: "list-1", newName: "New Name" });

    expect(
      screen.queryByRole("link", { name: "Weekly Shopping" }),
    ).not.toBeInTheDocument();
  });
});

// ─── CreateShoppingListModal ──────────────────────────────────────────────────

describe("CreateShoppingListModal", () => {
  it("renders the modal title", () => {
    render(<CreateShoppingListModal onClose={noop} onSuccess={noop} />);
    expect(screen.getByText("New shopping list")).toBeInTheDocument();
  });

  it("renders the name input field", () => {
    render(<CreateShoppingListModal onClose={noop} onSuccess={noop} />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("calls onClose when X button is clicked", () => {
    const onClose = vi.fn();
    render(<CreateShoppingListModal onClose={onClose} onSuccess={noop} />);
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("enables Create button after typing a name", () => {
    render(<CreateShoppingListModal onClose={noop} onSuccess={noop} />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Groceries" },
    });
    expect(screen.getByRole("textbox")).toHaveValue("Groceries");
  });

  it("renders Create and Cancel buttons", () => {
    render(<CreateShoppingListModal onClose={noop} onSuccess={noop} />);
    expect(screen.getByRole("button", { name: /create/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("keeps its buttons in the shared action row, which aligns them to the end", () => {
    render(<CreateShoppingListModal onClose={noop} onSuccess={noop} />);
    const row = screen.getByRole("button", { name: /cancel/i }).parentElement;
    expect(row).toHaveClass("justify-end");
    expect(screen.getByRole("button", { name: /create/i }).parentElement).toBe(
      row,
    );
    // The widths belong to the row (full width on a phone, intrinsic from sm:),
    // so a button that declares its own would split the dialog on a desktop.
    expect(
      screen.getByRole("button", { name: /cancel/i }).className,
    ).not.toMatch(/\bw-full\b/);
  });
});

// ─── AddToShoppingListButton ─────────────────────────────────────────────────

describe("AddToShoppingListButton", () => {
  it("renders the shopping cart button", () => {
    // The button is gated on the list's write key now, so the tests that
    // look at it hold it.
    signInWith(["shopping_lists:write"]);
    render(<AddToShoppingListButton data={{ item: makeItem() }} />);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("is not disabled when mutation is idle", () => {
    signInWith(["shopping_lists:write"]);
    render(<AddToShoppingListButton data={{ item: makeItem() }} />);
    expect(screen.getByRole("button")).not.toBeDisabled();
  });

  it("stays away from an account that may only read the list", () => {
    // The product sheet renders the button through the quick-action slot;
    // clicking it answered 403 for a viewer, after the product had been
    // found and the sheet opened.
    signInWith(["shopping_lists:read"]);
    render(<AddToShoppingListButton data={{ item: makeItem() }} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
