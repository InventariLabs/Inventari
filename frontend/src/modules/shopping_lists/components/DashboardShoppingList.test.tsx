import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import DashboardShoppingList from "./DashboardShoppingList";
import { tFor } from "@/test/mocks/i18n";

// The real translator, bound to the namespace the page uses. An identity
// stub would make every label assertion below pass on a missing translation.
const t = tFor("common");

const withRouter = (component: React.ReactElement) => (
  <MemoryRouter>{component}</MemoryRouter>
);

// ── DashboardShoppingList ─────────────────────────────────────────────────────

describe("DashboardShoppingList", () => {
  it("renders empty state when no active shopping list", () => {
    render(
      withRouter(<DashboardShoppingList activeShoppingList={null} t={t} />),
    );
    expect(
      screen.getByRole("link", { name: "Create list" }),
    ).toBeInTheDocument();
  });

  it("renders active shopping list name", () => {
    render(
      withRouter(
        <DashboardShoppingList
          activeShoppingList={{
            id: "list-1",
            name: "Weekly groceries",
            items: [],
          }}
          t={t}
        />,
      ),
    );
    expect(screen.getByText("Weekly groceries")).toBeInTheDocument();
  });

  it("shows how much of the list is already bought, as a count and a bar", () => {
    const { container } = render(
      withRouter(
        <DashboardShoppingList
          activeShoppingList={{
            id: "list-1",
            name: "Groceries",
            items: [
              { id: "i1", name: "Milk", is_purchased: false } as never,
              { id: "i2", name: "Bread", is_purchased: true } as never,
              { id: "i3", name: "Eggs", is_purchased: false } as never,
              { id: "i4", name: "Salt", is_purchased: true } as never,
            ],
          }}
          t={t}
        />,
      ),
    );
    expect(screen.getByText("2/4")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "2 of 4 bought" }),
    ).toBeInTheDocument();
    const fill = container.querySelector("[data-fill]") as HTMLElement;
    expect(parseFloat(fill.style.width)).toBe(50);
    expect(screen.getByRole("link", { name: "Groceries" })).toHaveAttribute(
      "href",
      "/shopping-lists/list-1",
    );
  });

  it("draws an empty bar for a list with nothing bought yet", () => {
    const { container } = render(
      withRouter(
        <DashboardShoppingList
          activeShoppingList={{
            id: "list-1",
            name: "Groceries",
            items: [{ id: "i1", name: "Milk", is_purchased: false } as never],
          }}
          t={t}
        />,
      ),
    );
    expect(screen.getByText("0/1")).toBeInTheDocument();
    expect(container.querySelector("[data-fill]")).toBeNull();
  });
});
