import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NeedsTable } from "./NeedsTable";
import type { NeedsView } from "@/modules/maker/types/maker";

const nextWeek = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);

const row = {
  template_id: "t-1",
  name: "Flour",
  uom_symbol: "kg",
  needed: "12",
  in_stock: "4",
  on_order: "3" as string | null,
  expected: [
    {
      purchase_order_id: "po-1",
      number: "PO-1",
      expected_date: nextWeek,
      quantity: "3",
    },
  ],
  missing: "5",
  planned: "0",
  action: "buy" as const,
};

const view = (over: Partial<NeedsView>): NeedsView => ({
  rows: [row],
  purchasing: true,
  run_count: 2,
  unmeasured: [],
  ...over,
});

describe("NeedsTable", () => {
  it("shows what is on order, with the order and its date", () => {
    render(<NeedsTable view={view({})} />);
    expect(
      screen.getByRole("columnheader", { name: "On order" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/PO-1/)).toBeInTheDocument();
  });

  it("has no on-order column at all while purchasing is off", () => {
    render(
      <NeedsTable
        view={view({
          purchasing: false,
          rows: [{ ...row, on_order: null, expected: [] }],
        })}
      />,
    );
    expect(
      screen.queryByRole("columnheader", { name: "On order" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(4);
  });

  it("marks an ingredient that has a recipe of its own as one to make", () => {
    render(
      <NeedsTable
        view={view({ rows: [{ ...row, name: "Dough", action: "make" }] })}
      />,
    );
    expect(screen.getByText("Make")).toBeInTheDocument();
  });

  it("says how much of a sub-assembly is already planned, and nothing otherwise", () => {
    render(
      <NeedsTable
        view={view({
          rows: [
            { ...row, name: "Dough", action: "make", planned: "5" },
            { ...row, template_id: "t-2", name: "Salt" },
          ],
        })}
      />,
    );
    expect(screen.getAllByText(/Planned:/)).toHaveLength(1);
    expect(screen.getByText("Planned: 5 kg")).toBeInTheDocument();
  });
});
