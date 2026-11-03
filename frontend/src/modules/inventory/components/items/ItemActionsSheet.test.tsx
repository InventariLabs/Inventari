import { render, screen } from "@/test/utils";
import { describe, it, expect, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import type { Item } from "@/types";
import ItemActionsSheet from "./ItemActionsSheet";

/**
 * The sheet behind a row's ⋮. Safest actions first, Delete below a divider and
 * routed to the page's ConfirmDialog. No "Details" — the row itself is that
 * action. The stock actions are spelled out here even though the card's ✓
 * covers one of them: on a touch screen no tooltip ever appears, and a finger
 * must be able to read what it is about to do to the stock.
 */

const item = {
  id: "item-1",
  name: "Rack 42U Open Frame",
  quantity: 3,
  organization_id: "org-1",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  ...({} as Partial<Item>),
} as Item;

const baseProps = () => ({
  open: true,
  onClose: vi.fn(),
  onConsume: vi.fn(),
  onAddOne: vi.fn(),
  onEdit: vi.fn(),
  onViewDetails: vi.fn(),
  onMove: vi.fn(),
  onSetThreshold: vi.fn(),
  onDelete: vi.fn(),
});

describe("ItemActionsSheet", () => {
  it("names the product it belongs to, on screen", () => {
    render(<ItemActionsSheet item={item} {...baseProps()} />);

    expect(
      screen.getByRole("heading", { name: "Rack 42U Open Frame" }),
    ).toBeInTheDocument();
  });

  it("keeps naming and acting on the tapped row when two share a name", async () => {
    const user = userEvent.setup();
    const first = {
      ...item,
      id: "item-1",
      quantity: "1",
      is_deleted: false,
    } as Item;
    const second = {
      ...item,
      id: "item-2",
      quantity: "2",
      is_deleted: false,
    } as Item;
    const props = baseProps();

    // Two rows, one name. The first row's sheet still knows which product
    // it was opened for — the header names it and Delete reaches item-1.
    const firstRender = render(<ItemActionsSheet item={first} {...props} />);
    expect(
      screen.getByRole("heading", { name: "Rack 42U Open Frame" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(props.onDelete).toHaveBeenCalledWith("item-1");
    firstRender.unmount();

    // The second row's ⋮ opens the same sheet with its own item; the name
    // is the same, the target is not.
    const secondProps = baseProps();
    render(<ItemActionsSheet item={second} {...secondProps} />);
    expect(
      screen.getByRole("heading", { name: "Rack 42U Open Frame" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(secondProps.onDelete).toHaveBeenCalledWith("item-2");
    expect(secondProps.onDelete).not.toHaveBeenCalledWith("item-1");
  });

  it("offers Edit, Move, Set stock alert and a separated Delete — and Product details first", () => {
    render(<ItemActionsSheet item={item} {...baseProps()} />);

    const sheet = screen.getByRole("dialog", { name: "Rack 42U Open Frame" });
    expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^move$/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /set stock alert/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^delete$/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^product details$/i }),
    ).toBeInTheDocument();
    expect(sheet).toBeInTheDocument();
  });

  it("hides Delete entirely when the list provides no delete handler", () => {
    const props = baseProps();
    render(<ItemActionsSheet item={item} {...props} onDelete={undefined} />);

    expect(screen.queryByRole("button", { name: /^delete$/i })).toBeNull();
  });

  it("hides Delete from a writer without items:delete, and keeps the rest", () => {
    // Deleting is `items:delete`; editing, moving and the alert are
    // `items:write`. A base-role member holds the second without the first,
    // and the sheet offered Delete on the strength of `items:write`.
    render(<ItemActionsSheet item={item} {...baseProps()} canDelete={false} />);

    expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^move$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^delete$/i })).toBeNull();
  });

  it("delegates Delete without deleting anything itself", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<ItemActionsSheet item={item} {...props} />);

    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    expect(props.onDelete).toHaveBeenCalledTimes(1);
    expect(props.onDelete).toHaveBeenCalledWith("item-1");
    expect(props.onClose).toHaveBeenCalled();
  });

  it("delegates Edit, Move and Set stock alert with the item", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<ItemActionsSheet item={item} {...props} />);

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    expect(props.onEdit).toHaveBeenCalledWith(item);
    expect(props.onClose).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /^move$/i }));
    expect(props.onMove).toHaveBeenCalledWith(item);

    await user.click(screen.getByRole("button", { name: /set stock alert/i }));
    expect(props.onSetThreshold).toHaveBeenCalledWith(item);
  });

  it("opens the product page from Product details, with the item", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<ItemActionsSheet item={item} {...props} />);

    await user.click(
      screen.getByRole("button", { name: /^product details$/i }),
    );
    expect(props.onViewDetails).toHaveBeenCalledWith(item);
    expect(props.onClose).toHaveBeenCalled();
  });

  it("lists the row's stock actions in words, so a finger can read them", async () => {
    // The row's stock actions are icons — check circle, + — and their words
    // live in a tooltip no finger ever sees. The menu spells the same actions
    // out: the same text the icons carry in their names.
    const user = userEvent.setup();
    const props = baseProps();
    render(<ItemActionsSheet item={item} {...props} />);

    await user.click(screen.getByRole("button", { name: /^remove 1 unit$/i }));
    expect(props.onConsume).toHaveBeenCalledWith("item-1");
    expect(props.onClose).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /^add 1 unit$/i }));
    expect(props.onAddOne).toHaveBeenCalledWith("item-1");
  });
});

describe("ItemActionsSheet — a used-up record", () => {
  it("offers no unit the server would refuse, and keeps Move", () => {
    render(
      <ItemActionsSheet
        {...baseProps()}
        item={{ ...item, quantity: 0, location_id: "consumed" } as Item}
        storages={
          [
            { id: "consumed", name: "Consumed (Virtual)", usage: "customer" },
          ] as never
        }
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Add 1 unit" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Move/ })).toBeInTheDocument();
  });
});
