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
            },
            {
              lot_id: "b",
              lot_name: "WB",
              status: "active",
              best_before: "2026-12-01",
            },
          ],
        }}
      />,
    );

    expect(screen.getByTestId("maker-record-batches")).toHaveTextContent(
      "WA, WB",
    );
    // Each batch keeps its own date: WB does not borrow WA's.
    expect(screen.getAllByText(/WB/)).toHaveLength(2);
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

  it("is the part of the page that prints", () => {
    render(<BatchRecordSheet record={record} />);

    expect(screen.getByTestId("maker-batch-record")).toHaveClass("print:block");
  });
});
