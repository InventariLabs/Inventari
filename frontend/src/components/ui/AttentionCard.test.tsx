import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import {
  AttentionCard,
  sortBySeverity,
  type AttentionItem,
} from "@/components/ui/AttentionCard";

const quiet = {
  okText: "All under control",
  linkLabel: "Products",
  linkHref: "/inventory/items",
};

const items: AttentionItem[] = [
  {
    id: "low",
    severity: "low",
    title: "Frozen peas",
    reason: "low stock · 1 pc",
    where: "Basement freezer",
    href: "/inventory/items/low",
  },
  {
    id: "info",
    severity: "info",
    title: "Draft count",
    reason: "not started",
    href: "/inventory/counts/1",
  },
  {
    id: "expired",
    severity: "expired",
    title: "UHT milk",
    reason: "expired yesterday",
    where: "Fridge",
    href: "/inventory/items/expired",
  },
  {
    id: "expiring",
    severity: "expiring",
    title: "Yoghurt",
    reason: "expires tomorrow",
    where: "Fridge",
    href: "/inventory/items/expiring",
  },
];

function renderCard(props: Partial<Parameters<typeof AttentionCard>[0]> = {}) {
  return render(
    <MemoryRouter>
      <AttentionCard
        items={items}
        attentionLabel="4 items need attention"
        summary="84 products in 6 places"
        linkLabel="All"
        linkHref="/inventory/items"
        quiet={quiet}
        {...props}
      />
    </MemoryRouter>,
  );
}

describe("sortBySeverity", () => {
  it("puts expired first, then expiring, then low stock, then information", () => {
    expect(sortBySeverity(items).map((i) => i.id)).toEqual([
      "expired",
      "expiring",
      "low",
      "info",
    ]);
  });

  it("keeps the caller's order within one severity", () => {
    const same: AttentionItem[] = [
      { ...items[2], id: "a" },
      { ...items[2], id: "b" },
    ];
    expect(sortBySeverity(same).map((i) => i.id)).toEqual(["a", "b"]);
  });
});

describe("AttentionCard with something to report", () => {
  it("lists the rows by severity, each name a link to its record", () => {
    renderCard();
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((r) => within(r).getByRole("link").textContent)).toEqual([
      "UHT milk",
      "Yoghurt",
      "Frozen peas",
      "Draft count",
    ]);
    expect(within(rows[0]).getByRole("link")).toHaveAttribute(
      "href",
      "/inventory/items/expired",
    );
    // On a phone this link measured 312x20 — the name is the line, and the
    // line is 20px tall. text-sm sits on a 20px line, so 12px of padding a
    // side is the 44px floor below `md`, and the desktop row gives most of
    // it back.
    expect(within(rows[0]).getByRole("link").className).toContain("py-3");
    expect(within(rows[0]).getByRole("link").className).toContain("md:py-1");
  });

  it("leads with the count and the summary", () => {
    renderCard();
    expect(
      screen.getByRole("heading", { name: "4 items need attention" }),
    ).toBeInTheDocument();
    expect(screen.getByText("84 products in 6 places")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All" })).toHaveAttribute(
      "href",
      "/inventory/items",
    );
  });

  it("lets the actions fall under the heading instead of squeezing it", () => {
    // With an action beside the link the heading was left ~60px at 390px and
    // printed one word per line. jsdom has no layout, so this pins the rule:
    // the row wraps, and the heading group keeps a floor of its own.
    renderCard({ actions: <button type="button">Do something</button> });
    const heading = screen.getByRole("heading", {
      name: "4 items need attention",
    });
    const group = heading.parentElement?.parentElement;
    expect(group?.className).toContain("basis-48");
    expect(group?.parentElement?.className).toContain("flex-wrap");
    expect(screen.getByRole("link", { name: "All" }).parentElement).toBe(
      group?.parentElement,
    );
  });

  it("keeps a card without actions on one row, the link beside the heading", () => {
    // The wrap exists for the actions. Without them it moved the link under
    // the heading at 320px, a change nobody asked of the equipment overview.
    renderCard();
    const heading = screen.getByRole("heading", {
      name: "4 items need attention",
    });
    const group = heading.parentElement?.parentElement;
    expect(group?.className).not.toContain("basis-48");
    expect(group?.parentElement?.className).not.toContain("flex-wrap");
    expect(screen.getByRole("link", { name: "All" }).parentElement).toBe(
      group?.parentElement,
    );
  });

  it("renders the location on every width — it wraps, it is not hidden", () => {
    // jsdom has no stylesheet, so the classes are all there is to read — and
    // on the whole way up: `hidden sm:flex` on a wrapper hides the place as
    // surely as on its own span.
    const hides = /^(?:.+:)?(?:hidden|invisible|sr-only)$/;
    renderCard();
    const where = screen.getAllByText("Fridge");
    expect(where).toHaveLength(2);
    for (const el of where) {
      for (let at: Element | null = el; at; at = at.parentElement) {
        expect([...at.classList].filter((c) => hides.test(c))).toEqual([]);
      }
    }
  });

  it("caps the rows and leaves the rest to the link", () => {
    renderCard({ maxItems: 2 });
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the rest itself when its link does not open them", async () => {
    renderCard({ maxItems: 2, showAllLabel: "Show all 4" });
    await userEvent.click(screen.getByRole("button", { name: "Show all 4" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(items.length);
    expect(screen.queryByRole("button", { name: "Show all 4" })).toBeNull();
  });

  it("offers nothing to show when every row is already there", () => {
    renderCard({ showAllLabel: "Show all 4" });
    expect(screen.queryByRole("button", { name: "Show all 4" })).toBeNull();
  });

  it("opens a record from the name's link, and from nowhere else on the row", async () => {
    // React delegates onClick, so a clickable div carries no attribute to find
    // in the DOM. Only clicking it can tell.
    const user = userEvent.setup();
    const CurrentPath = () => <output>{useLocation().pathname}</output>;
    renderCard({ actions: <CurrentPath /> });
    const row = screen.getAllByRole("listitem")[0];

    await user.click(within(row).getByText("expired yesterday"));
    await user.click(row);
    expect(screen.getByRole("status")).toHaveTextContent(/^\/$/);

    await user.click(within(row).getByRole("link", { name: "UHT milk" }));
    expect(screen.getByRole("status")).toHaveTextContent(
      "/inventory/items/expired",
    );
  });
});

describe("AttentionCard on a quiet day", () => {
  it("collapses to one line with the summary and a link, and no rows", () => {
    renderCard({ items: [] });
    expect(
      screen.getByRole("heading", { name: "All under control" }),
    ).toBeInTheDocument();
    expect(screen.getByText("84 products in 6 places")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Products" })).toHaveAttribute(
      "href",
      "/inventory/items",
    );
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.queryByText("4 items need attention")).toBeNull();
  });

  it("still draws the actions: a quiet day is when a card's note matters most", () => {
    // A product with stock in use outside the shelves raises no alert, and the
    // note that explains it lives in the actions. Dropping them on the quiet
    // line left the screen silent exactly in that case.
    renderCard({ items: [], actions: <p>Stock in use is not counted</p> });
    expect(screen.getByText("Stock in use is not counted")).toBeInTheDocument();
  });
});

describe("AttentionCard when the answer did not arrive", () => {
  it("never claims everything is under control", async () => {
    const onRetry = vi.fn();
    renderCard({
      items: [],
      unavailable: {
        message: "The numbers could not be loaded.",
        retryLabel: "Try again",
        onRetry,
      },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The numbers could not be loaded.",
    );
    expect(screen.queryByText("All under control")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("keeps the rows it does have beside the alert", () => {
    renderCard({
      unavailable: {
        message: "Part of the numbers could not be loaded.",
        retryLabel: "Try again",
        onRetry: () => {},
      },
    });
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
  });
});

describe("AttentionCard heading beside a failed source", () => {
  it("drops the count it cannot vouch for", () => {
    renderCard({
      unavailable: {
        message: "Part of the numbers could not be loaded.",
        retryLabel: "Try again",
        onRetry: () => {},
        partialLabel: "Needs attention",
      },
    });
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.queryByText("4 items need attention")).toBeNull();
  });
});

describe("AttentionCard — while the answer is on its way", () => {
  it("says neither 'all under control' nor 'needs attention' before it knows", () => {
    // The rows arrive empty before the requests do, and an empty list is
    // exactly what the quiet line is drawn from: without a loading state the
    // card announced a quiet day on every visit, then took it back.
    renderCard({ items: [], loading: true });
    expect(screen.queryByText("All under control")).toBeNull();
    expect(screen.queryByText("4 items need attention")).toBeNull();
    expect(document.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("lets a failure through while the rest is still loading", () => {
    renderCard({
      items: [],
      loading: true,
      unavailable: {
        message: "Could not check",
        retryLabel: "Retry",
        onRetry: vi.fn(),
      },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Could not check");
  });
});
