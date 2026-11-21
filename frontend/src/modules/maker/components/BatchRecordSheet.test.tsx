import { describe, expect, it } from "vitest";
import { render, screen, within } from "@/test/utils";
import { BatchRecordSheet } from "@/modules/maker/components/BatchRecordSheet";
import type { BatchRecord } from "@/modules/maker/types/maker";

const record: BatchRecord = {
  order_id: "ord-1",
  number: "PR/2026/0007",
  status: "COMPLETED",
  output_template_name: "Rye bread",
  recipe_name: "Sourdough loaf",
  output_uom_symbol: "pcs",
  planned_qty: "2",
  actual_qty: "2",
  output_lot_name: "20261103-1",
  production_date: "2026-11-03",
  best_before: "2026-11-10",
  output_location_name: "Bakery shelf",
  uncosted_ingredients: 0,
  ingredients: [
    {
      template_id: "flour",
      template_name: "Rye flour",
      unit: "kg",
      consumed_qty: "1",
      cost: "2.00",
      unit_cost: "2",
      batches: [
        {
          lot_id: "f-07",
          lot_name: "F-07",
          expiry_date: "2026-03-01",
          quantity: "1",
        },
      ],
    },
  ],
  material_cost: "2.00",
  total_cost: "2.00",
  created_by_name: "Ada Baker",
  created_at: "2026-11-03T06:00:00Z",
  completed_by_name: "Ada Baker",
  completed_at: "2026-11-03T09:00:00Z",
  notes: "Proofed overnight",
  attachments: [
    {
      id: "att-1",
      production_order_id: "ord-1",
      original_name: "loaves.jpg",
      content_type: "image/jpeg",
      size_bytes: 1200,
      url: "/uploads/x",
      created_at: "2026-11-03T09:05:00Z",
    },
  ],
};

describe("BatchRecordSheet for a run filled in portions", () => {
  it("names every batch the output was filed under, with its best-before", () => {
    render(
      <BatchRecordSheet
        record={{
          ...record,
          output_lot_name: "WA",
          output_batches: [
            {
              lot_id: "a",
              lot_name: "WA",
              status: "active",
              best_before: "2026-11-10",
              quantity: "4",
            },
            {
              lot_id: "b",
              lot_name: "WB",
              status: "quarantined",
              status_reason: "Cloudy",
              best_before: "2026-11-09",
              quantity: "3",
            },
          ],
        }}
      />,
    );

    // A recall reader can say how much of which batch exists.
    const batches = screen.getByTestId("maker-record-batches");
    expect(batches).toHaveTextContent(/WA — 4/);
    expect(batches).toHaveTextContent(/WB — 3/);
    // Each batch keeps its own date: WB does not borrow WA's.
    expect(screen.getAllByText(/WB/).length).toBeGreaterThanOrEqual(2);
    // The hold and its reason are on the record.
    expect(screen.getByTestId("maker-batch-hold-note")).toHaveTextContent(
      "WB — Quarantined: Cloudy",
    );
  });
});

describe("BatchRecordSheet", () => {
  it("names every ingredient with the batch and quantity it came from", () => {
    render(<BatchRecordSheet record={record} />);

    const sheet = screen.getByTestId("maker-batch-record");
    expect(within(sheet).getByText("Rye bread")).toBeInTheDocument();
    expect(within(sheet).getByText("Sourdough loaf")).toBeInTheDocument();
    expect(within(sheet).getByText("20261103-1")).toBeInTheDocument();
    expect(within(sheet).getByText("Rye flour")).toBeInTheDocument();
    expect(within(sheet).getByText(/^F-07 — /)).toBeInTheDocument();
    expect(within(sheet).getByText("Proofed overnight")).toBeInTheDocument();
    expect(within(sheet).getByText("loaves.jpg")).toBeInTheDocument();
    expect(within(sheet).getAllByText(/Ada Baker/)).toHaveLength(2);
  });

  it("prints the expiry of a record kept without a batch name", () => {
    render(
      <BatchRecordSheet
        record={{
          ...record,
          ingredients: [
            {
              ...record.ingredients![0],
              batches: [
                {
                  lot_id: null,
                  lot_name: null,
                  expiry_date: "2026-06-01",
                  quantity: "6",
                },
              ],
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/no batch — 6/i)).toHaveTextContent(/2026/);
  });

  it("says a total leaves out an ingredient drawn with no cost", () => {
    const { rerender } = render(<BatchRecordSheet record={record} />);
    expect(screen.queryByText(/no rate|no cost/i)).toBeNull();

    rerender(
      <BatchRecordSheet record={{ ...record, uncosted_ingredients: 1 }} />,
    );

    expect(screen.getByText(/missing from this figure/i)).toBeInTheDocument();
  });

  it("is the part of the page that prints", () => {
    render(<BatchRecordSheet record={record} />);

    expect(screen.getByTestId("maker-batch-record")).toHaveClass("print:block");
  });
});
