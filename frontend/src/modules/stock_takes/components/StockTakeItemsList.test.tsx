import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Item } from "@/types";
import type { StockTakeItem } from "@/modules/stock_takes/types/stock-takes";
import StockTakeItemsList from "./StockTakeItemsList";

/**
 * Two receipts and a putaway into one place: three records of one cable
 * that differ in nothing but when they came in. Listed newest first, so the
 * order the rows are numbered in is the list's own, not the input's.
 */
const added = {
  "cable-c": "2026-10-31T14:30:00Z",
  "cable-a": "2026-10-31T09:05:00Z",
  "cable-b": "2026-10-31T11:40:00Z",
} as const;
const ids = Object.keys(added) as (keyof typeof added)[];

function renderList(showDiscrepancies: boolean) {
  render(
    <StockTakeItemsList
      allItemIds={ids}
      showDiscrepancies={showDiscrepancies}
      countedQuantities={{}}
      notes={{}}
      reasons={{}}
      triedToSave={{}}
      reasonRequired={false}
      stockTakeStatus="in_progress"
      blindMode={true}
      isUpdatePending={false}
      locationLevelFilter=""
      shelfId={null}
      getItemById={(id) =>
        ({
          id,
          name: "USB-C Cable 1m",
          created_at: added[id as keyof typeof added],
        }) as unknown as Item
      }
      getStockTakeItem={(id) =>
        ({
          id,
          item_id: id,
          item_name: "USB-C Cable 1m",
          location_id: "dock",
          shelf_location: "Dock",
        }) as unknown as StockTakeItem
      }
      // The first record is the one the count found right.
      hasDiscrepancy={(id) => id !== "cable-a"}
      getDiscrepancyType={() => null}
      isUnsaved={() => false}
      onNoteChange={() => {}}
      onReasonChange={() => {}}
      onQuantityChange={() => {}}
      onQuantityStep={() => {}}
      onSave={() => {}}
      onRequestRecount={() => {}}
    />,
  );
  return screen
    .getAllByRole("textbox", { name: /^Counted quantity of USB-C Cable/ })
    .map((field) => field.getAttribute("aria-label") ?? "");
}

describe("StockTakeItemsList — records of one product in one place", () => {
  it("tells the records apart by when each came in, numbered in that order", () => {
    const names = renderList(false);
    expect(new Set(names).size).toBe(3);
    // Listed in the order they came in, the order of their numbers.
    expect(names.map((n) => n.match(/Record (\d)/)?.[1])).toEqual([
      "1",
      "2",
      "3",
    ]);
    const cableA = names.find((name) => name.includes("Record 1 of 3"));
    // Each record carries the moment it was added, not only a number.
    expect(cableA).toMatch(/added /);
    expect(new Set(names.map((n) => n.replace(/.*added /, ""))).size).toBe(3);
  });

  it("keeps a record's number when the discrepancy filter hides its siblings", () => {
    const all = renderList(false);
    document.body.innerHTML = "";
    const filtered = renderList(true);
    expect(filtered).toHaveLength(2);
    for (const name of filtered) expect(all).toContain(name);
  });
});
