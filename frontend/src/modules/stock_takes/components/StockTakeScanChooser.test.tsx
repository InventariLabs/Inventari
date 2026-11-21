import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import StockTakeScanChooser from "./StockTakeScanChooser";
import type { Item } from "@/types";
import type { StockTakeItem } from "../types/stock-takes";

const row = (over: Partial<StockTakeItem>): StockTakeItem =>
  ({
    id: "row-1",
    item_id: "item-1",
    item_name: "Basmati rice",
    shelf_location: "Aisle 2",
    lot_name: null,
    ...over,
  }) as StockTakeItem;

const expiring = {
  effective_expiry_date: new Date(Date.now() + 90 * 86_400_000)
    .toISOString()
    .slice(0, 10),
} as unknown as Item;

describe("StockTakeScanChooser", () => {
  it("tells two batches of one product apart by the number on the pack", () => {
    render(
      <StockTakeScanChooser
        rows={[
          row({ id: "a", item_id: "item-a", lot_name: "LOT-A" }),
          row({ id: "b", item_id: "item-b", lot_name: "LOT-B" }),
        ]}
        getItemById={() => expiring}
        onChoose={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/LOT-A/)).toBeInTheDocument();
    expect(screen.getByText(/LOT-B/)).toBeInTheDocument();
    expect(screen.getAllByText(/Aisle 2/)).toHaveLength(2);
  });

  it("leaves the batch out for a row that has none", () => {
    render(
      <StockTakeScanChooser
        rows={[row({}), row({ id: "b", item_id: "item-b" })]}
        getItemById={() => undefined}
        onChoose={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByText(/Batch/)).toBeNull();
  });
});
