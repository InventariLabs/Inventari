import { render, screen, fireEvent, act, within } from "@/test/utils";
import { describe, it, expect, vi, afterEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import type { Item } from "@/types";
import ItemMobileCard from "./ItemMobileCard";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), dismiss: vi.fn() },
}));

/**
 * the card's text block used to be a `<div onClick>` — invisible to
 * keyboards and announced as plain text by screen readers. It is a real
 * button now, named after the product it opens.
 */

const makeItem = (overrides: Partial<Item> = {}): Item =>
  ({
    id: "item-1",
    name: "Rack 42U Open Frame",
    quantity: 3,
    organization_id: "org-1",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    is_deleted: false,
    ...overrides,
  }) as Item;

const baseProps = () => ({
  storages: [],
  categories: [],
  onItemClick: vi.fn(),
  onConsume: vi.fn(),
  onSetThreshold: vi.fn(),
  onOpenActions: vi.fn(),
  consumingId: null,
  isSelected: false,
  onToggleSelect: vi.fn(),
  onSwipeDelete: vi.fn(),
});

describe("ItemMobileCard — row as a button", () => {
  it("exposes the product name as a button", () => {
    const props = baseProps();
    render(<ItemMobileCard item={makeItem()} {...props} />);

    expect(
      screen.getByRole("button", { name: /^Rack 42U Open Frame/ }),
    ).toBeInTheDocument();
  });

  it("fires onItemClick exactly once on Enter", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<ItemMobileCard item={makeItem()} {...props} />);

    const target = screen.getByRole("button", { name: /^Rack 42U Open Frame/ });
    target.focus();
    await user.keyboard("{Enter}");

    expect(props.onItemClick).toHaveBeenCalledTimes(1);
    expect(props.onItemClick).toHaveBeenCalledWith(
      expect.objectContaining({ id: "item-1" }),
    );
  });

  it("keeps the quantity badge out of the row button", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<ItemMobileCard item={makeItem()} {...props} />);

    // The badge is a separate control — activating it opens the threshold
    // dialog and must not bubble into the row's open action.
    await user.click(screen.getByTitle("Set stock alert"));
    expect(props.onSetThreshold).toHaveBeenCalledTimes(1);
    expect(props.onItemClick).not.toHaveBeenCalled();

    // …and structurally: no button nested inside the row button.
    const rowButton = screen.getByRole("button", {
      name: /^Rack 42U Open Frame/,
    });
    expect(rowButton.querySelector("button")).toBeNull();
  });

  it("still fires onItemClick on a plain tap of the text block", () => {
    const props = baseProps();
    render(<ItemMobileCard item={makeItem()} {...props} />);

    fireEvent.click(
      screen.getByRole("button", { name: /^Rack 42U Open Frame/ }),
    );
    expect(props.onItemClick).toHaveBeenCalledTimes(1);
  });
});

describe("ItemMobileCard — actions trigger", () => {
  it("opens the actions sheet instead of replaying the row tap", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<ItemMobileCard item={makeItem()} {...props} />);

    await user.click(
      screen.getByRole("button", {
        name: "Product actions: Rack 42U Open Frame",
      }),
    );

    expect(props.onOpenActions).toHaveBeenCalledTimes(1);
    expect(props.onOpenActions).toHaveBeenCalledWith(
      expect.objectContaining({ id: "item-1" }),
    );
    expect(props.onItemClick).not.toHaveBeenCalled();
  });
});

describe("ItemMobileCard — the actions button names its product", () => {
  it("tells two cards' buttons apart", () => {
    render(
      <>
        <ItemMobileCard item={makeItem()} {...baseProps()} />
        <ItemMobileCard
          item={makeItem({ id: "item-2", name: "Hex nut 120" })}
          {...baseProps()}
        />
      </>,
    );

    expect(
      screen.getByRole("button", { name: "Product actions: Hex nut 120" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Product actions: Rack 42U Open Frame",
      }),
    ).toBeInTheDocument();
  });
});

describe("ItemMobileCard — quick actions keep their own touch targets", () => {
  // jsdom has no layout, so this pins the classes that make the geometry:
  // two full 44 px buttons in one column, spaced by a gap, with nothing that
  // grows a hit area past its box (a pseudo-element inset, a negative margin).
  // Measured in a browser at 390, 360 and 320 px: 44x44 each, no overlap
  // between the buttons of a row or of neighbouring rows.
  it("gives each action a 44 px box and spaces them instead of overlapping them", () => {
    render(<ItemMobileCard item={makeItem()} {...baseProps()} />);

    const remove = screen.getByRole("button", { name: "Remove 1 unit" });
    const more = screen.getByRole("button", {
      name: "Product actions: Rack 42U Open Frame",
    });

    for (const button of [remove, more]) {
      expect(button.className).toContain("h-11");
      expect(button.className).toContain("w-11");
      expect(button.className).not.toMatch(/after:|-m[trblxy]?-/);
    }
    expect(remove.parentElement).toBe(more.parentElement);
    expect(remove.parentElement?.className).toMatch(/\bflex-col\b/);
    expect(remove.parentElement?.className).toMatch(/\bgap-/);
  });

  it("offers no add action on the phone card, so a tap cannot add stock", () => {
    render(<ItemMobileCard item={makeItem()} {...baseProps()} />);

    expect(screen.queryByRole("button", { name: /add 1/i })).toBeNull();
  });
});

/**
 * The badge shows the quantity over its unit and was named by an
 * `aria-label` that spelled them "3 kg" mid-sentence; axe reads the shown
 * parts as one run — "3kg" — so the name did not contain what the badge
 * shows (WCAG 2.5.3, `label-content-name-mismatch`).
 */
it("ItemMobileCard — starts the badge's name with the quantity and unit it shows", () => {
  render(
    <ItemMobileCard
      item={makeItem({ uom: { symbol: "kg" } as Item["uom"] })}
      {...baseProps()}
    />,
  );

  const badge = screen.getByTitle("Set stock alert");
  // The shown parts joined as axe joins inline elements: without a space.
  const shown = Array.from(badge.children)
    .filter((el) => !el.classList.contains("sr-only"))
    .map((el) => el.textContent)
    .join("");
  expect(shown).toBe("3kg");
  expect(badge).toHaveAccessibleName(/^3kg\b.*set stock alert for rack 42u/i);
  expect(badge).not.toHaveAttribute("aria-label");
});

it("ItemMobileCard — shows a partly used pack as the fraction left", () => {
  render(
    <ItemMobileCard
      item={makeItem({
        quantity: "0.900",
        uom: { symbol: "pack", rounding: "1.000000" } as Item["uom"],
      })}
      {...baseProps()}
    />,
  );

  expect(screen.getByTitle("Set stock alert").children[0]).toHaveTextContent(
    /^0\.9$/,
  );
});

it("ItemMobileCard — keeps the unit in the name of the badge over a photo", () => {
  render(
    <ItemMobileCard
      item={makeItem({
        image_url: "/rack.jpg",
        uom: { symbol: "kg" } as Item["uom"],
      })}
      {...baseProps()}
    />,
  );

  // The photo leaves room for the number alone; the name still says the unit.
  expect(screen.getByTitle("Set stock alert")).toHaveAccessibleName(
    /^3\b.*kg.*set stock alert for rack 42u/i,
  );
});

describe("ItemMobileCard — selection mode", () => {
  it("swaps the quantity badge for a checkbox and the row tap for a toggle", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(<ItemMobileCard item={makeItem()} {...props} selectionMode />);

    // Checkbox where the quantity badge used to be…
    expect(
      screen.getByRole("checkbox", { name: /rack 42u/i }),
    ).toBeInTheDocument();
    expect(screen.queryByTitle("Set stock alert")).toBeNull();
    // …and the quick actions stand down so the models never share the card.
    expect(
      screen.queryByRole("button", { name: /product actions/i }),
    ).toBeNull();

    // The row tap toggles selection instead of opening the product.
    await user.click(
      screen.getByRole("button", { name: /^Rack 42U Open Frame/ }),
    );
    expect(props.onToggleSelect).toHaveBeenCalledTimes(1);
    expect(props.onToggleSelect).toHaveBeenCalledWith("item-1");
    expect(props.onItemClick).not.toHaveBeenCalled();
  });
});

describe("ItemMobileCard — low stock speaks in a word", () => {
  it("shows the warning badge only below the threshold", () => {
    const props = baseProps();
    render(
      <ItemMobileCard
        item={makeItem({ quantity: "1", min_quantity: 2 })}
        {...props}
      />,
    );
    expect(screen.getByText("Low")).toBeInTheDocument();
  });

  it("carries no signal when the threshold is set but met", () => {
    const props = baseProps();
    const { container } = render(
      <ItemMobileCard
        item={makeItem({ quantity: "10", min_quantity: 2 })}
        {...props}
      />,
    );
    expect(screen.queryByText("Low")).toBeNull();
    expect(container.querySelector('[class*="border-l-amber"]')).toBeNull();
  });

  it("carries no signal without a threshold", () => {
    const props = baseProps();
    const { container } = render(
      <ItemMobileCard item={makeItem({ min_quantity: null })} {...props} />,
    );
    expect(screen.queryByText("Low")).toBeNull();
    expect(container.querySelector('[class*="border-l-amber"]')).toBeNull();
  });
});

/**
 * `aria-label={item.name}` replaced the name computed from the
 * content, so location, barcode, SKU, the expiry badge and the "Low" badge
 * added by stopped being announced — the badge spoke to the eye only.
 */
describe("ItemMobileCard — the row name carries its metadata", () => {
  it("announces the low-stock word as part of the row name", () => {
    const props = baseProps();
    render(
      <ItemMobileCard
        item={makeItem({
          quantity: "1",
          min_quantity: 2,
          template: { sku: "SKU-9001" } as Item["template"],
        })}
        {...props}
      />,
    );

    const row = screen.getByRole("button", { name: /low/i });
    expect(row).toHaveAccessibleName(/Rack 42U Open Frame/);
    expect(row).toHaveAccessibleName(/SKU-9001/);
  });

  it("still opens the product exactly once on click and on Enter", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(
      <ItemMobileCard
        item={makeItem({ quantity: "1", min_quantity: 2 })}
        {...props}
      />,
    );

    const row = screen.getByRole("button", { name: /^Rack 42U Open Frame/ });
    await user.click(row);
    expect(props.onItemClick).toHaveBeenCalledTimes(1);

    row.focus();
    await user.keyboard("{Enter}");
    expect(props.onItemClick).toHaveBeenCalledTimes(2);
  });
});

/**
 * the swipe used to announce "<name> removed" and then, five seconds
 * later, open a confirmation dialog — the toast said the deed was done while
 * the deed had not started. The Undo window is the confirmation now, so the
 * gesture deletes for real and the wording promises exactly that.
 */
describe("ItemMobileCard — swipe to delete keeps its word", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  const swipeLeft = (card: HTMLElement) => {
    fireEvent.touchStart(card, { touches: [{ clientX: 300, clientY: 100 }] });
    fireEvent.touchMove(card, { touches: [{ clientX: 100, clientY: 100 }] });
    fireEvent.touchEnd(card);
  };

  /** Renders the toast body sonner was handed, so its wording can be read. */
  const renderToastBody = () => {
    const body = vi.mocked(toast.success).mock.calls[0][0];
    if (typeof body !== "function") throw new Error("toast body is not a node");
    return render(<>{body()}</>);
  };

  it("deletes once the Undo window closes, without a second question", () => {
    vi.useFakeTimers();
    const props = baseProps();
    render(<ItemMobileCard item={makeItem()} {...props} />);

    swipeLeft(screen.getByTestId("item-row"));

    // Nothing yet: the window is the user's chance to take it back.
    expect(props.onSwipeDelete).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(props.onSwipeDelete).toHaveBeenCalledTimes(1);
    expect(props.onSwipeDelete).toHaveBeenCalledWith("item-1");
  });

  it("says what is about to happen, in the user's language", () => {
    const props = baseProps();
    render(<ItemMobileCard item={makeItem()} {...props} />);

    swipeLeft(screen.getByTestId("item-row"));

    const { getByText, getByRole } = renderToastBody();
    expect(
      getByText(/Rack 42U Open Frame will be deleted/i),
    ).toBeInTheDocument();
    expect(getByRole("button", { name: /undo/i })).toBeInTheDocument();
  });

  it("cancels the deletion when Undo is pressed", () => {
    // Fake timers from the start: the Undo click has to land inside the same
    // window the deletion is waiting on. (fireEvent, not userEvent — the
    // latter schedules its own real timers.)
    vi.useFakeTimers();
    const props = baseProps();
    render(<ItemMobileCard item={makeItem()} {...props} />);

    swipeLeft(screen.getByTestId("item-row"));

    const { getByRole } = renderToastBody();
    fireEvent.click(getByRole("button", { name: /undo/i }));

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(props.onSwipeDelete).not.toHaveBeenCalled();
    expect(toast.dismiss).toHaveBeenCalled();
  });

  it("takes a scheduled delete back when the card unmounts inside the window", () => {
    vi.useFakeTimers();
    const props = baseProps();
    const { unmount } = render(<ItemMobileCard item={makeItem()} {...props} />);

    swipeLeft(screen.getByTestId("item-row"));
    unmount();
    act(() => {
      vi.advanceTimersByTime(6000);
    });

    // The positive control for the test below: the unmount alone does take
    // the pending window back.
    expect(props.onSwipeDelete).not.toHaveBeenCalled();
  });

  it("a second swipe takes the first promise back — no delete fires for a dead card", () => {
    // Two swipes inside the window arm two timers. Overwriting the cancel
    // ref without RELEASING the previous cancel orphans the first timer: it
    // fired once after the card was gone (measured). The assertion sits
    // behind the whole window, after the unmount — nothing may fire for an
    // audience that has left.
    vi.useFakeTimers();
    const props = baseProps();
    const { unmount } = render(<ItemMobileCard item={makeItem()} {...props} />);

    swipeLeft(screen.getByTestId("item-row"));
    swipeLeft(screen.getByTestId("item-row"));
    unmount();
    act(() => {
      vi.advanceTimersByTime(6000);
    });

    expect(props.onSwipeDelete).not.toHaveBeenCalled();
  });
});

/**
 * the row button drew Chrome's default outline instead of the
 * app's ring, and the quantity badge — which opens the threshold dialog —
 * announced itself as "3" or "3 PCS.", because a `title` names nothing that
 * already has content.
 */
describe("ItemMobileCard — focus ring and the quantity badge's name", () => {
  it("names the quantity badge after what it does", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    render(
      <ItemMobileCard
        item={makeItem({
          quantity: "3",
          uom: { symbol: "pcs" },
        } as Partial<Item>)}
        {...props}
      />,
    );

    const badge = screen.getByRole("button", { name: /set stock alert/i });
    expect(badge).toHaveAccessibleName(/Rack 42U Open Frame/);
    expect(badge).toHaveAccessibleName(/3/);

    await user.click(badge);
    expect(props.onSetThreshold).toHaveBeenCalledTimes(1);
  });

  it("draws the app's focus ring on the row button", () => {
    const props = baseProps();
    render(<ItemMobileCard item={makeItem()} {...props} />);

    const row = screen.getByRole("button", { name: /^Rack 42U Open Frame/ });
    expect(row.className).toContain("focus-visible:ring-2");
    expect(row.className).toContain("focus-visible:ring-ring");
    expect(row.className).toContain("focus-visible:outline-none");
  });
});

/**
 * The card's quick actions are icon-only — on a phone no tooltip ever
 * appears, so the words also live in the row's menu — but a pointer or a
 * keyboard reaching the card still has to read what the icons do. Same
 * mechanism as the desktop row: a tooltip of the app's own on hover and
 * focus, carrying the accessible name's words.
 */
describe("ItemMobileCard — quick actions carry their words", () => {
  // The tooltip carries the visible words; the accessible name may add to
  // them (here the product), and must start with them (WCAG 2.5.3).
  const NAMES = [
    ["Remove 1 unit", "Remove 1 unit"],
    ["Product actions: Rack 42U Open Frame", "Product actions"],
  ];

  it("shows every icon action's words in a tooltip, the same words as its name", () => {
    render(<ItemMobileCard item={makeItem()} {...baseProps()} />);

    for (const [name, words] of NAMES) {
      const button = screen.getByRole("button", { name });
      const tip = within(button).getByRole("tooltip");
      expect(tip).toHaveTextContent(words);
      expect(button.getAttribute("aria-label")).toContain(
        tip.textContent ?? "",
      );
    }
  });

  it("reveals the tooltip on hover and on focus, and keeps it clear of the card's clip", () => {
    // The card is `overflow-hidden` (the swipe moves it), so a bubble above
    // the button is cut at the card's edge. It opens to the left, over the
    // card's own content, where the card lets it through.
    render(<ItemMobileCard item={makeItem()} {...baseProps()} />);

    for (const [name] of NAMES) {
      const button = screen.getByRole("button", { name });
      const tip = within(button).getByRole("tooltip");
      expect(button.className).toContain("group/tooltip");
      expect(tip.className).toContain("group-hover/tooltip:opacity-100");
      expect(tip.className).toContain("group-focus-within/tooltip:opacity-100");
      expect(tip.className).toContain("pointer-events-none");
      expect(tip.className).toContain("right-full");
    }
  });
});

describe("ItemMobileCard — an account that cannot write", () => {
  it.each([
    ["with a photo", { image_url: "https://example.test/rack.jpg" }],
    ["without a photo", {}],
  ])("shows the quantity but offers no stock alert %s", (_label, extra) => {
    render(
      <ItemMobileCard
        item={makeItem({ quantity: "3", ...extra } as Partial<Item>)}
        {...baseProps()}
        canWrite={false}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /set stock alert/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTitle("Set stock alert")).not.toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("still opens the actions sheet, the only way from the list to the product page, and offers no consume", async () => {
    const props = baseProps();
    render(<ItemMobileCard item={makeItem()} {...props} canWrite={false} />);

    expect(
      screen.queryByRole("button", { name: /consume/i }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", {
        name: "Product actions: Rack 42U Open Frame",
      }),
    );
    expect(props.onOpenActions).toHaveBeenCalledTimes(1);
  });
});

describe("ItemMobileCard — a used-up record", () => {
  it("says used up, not the name of the system's place for it", () => {
    render(
      <ItemMobileCard
        item={makeItem({
          quantity: 0,
          location_id: "consumed",
        } as Partial<Item>)}
        {...baseProps()}
        storages={
          [
            { id: "consumed", name: "Consumed (Virtual)", usage: "customer" },
          ] as never
        }
      />,
    );

    expect(screen.getByText("Used up")).toBeInTheDocument();
    expect(screen.queryByText("Consumed (Virtual)")).not.toBeInTheDocument();
  });
});
