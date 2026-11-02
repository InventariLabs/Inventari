import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import StockTakeItemCardHeader from "./StockTakeItemCardHeader";
import type { ComponentProps } from "react";

type Props = ComponentProps<typeof StockTakeItemCardHeader>;

describe("StockTakeItemCardHeader — location chip", () => {
  it("reads in text-on-secondary on its surface-raised fill, never text-on-muted", () => {
    // Muted text on surface-raised measures 4.07:1 dark / 4.40:1 light at
    // 12px (UI_GUIDELINES §1.2); on-secondary clears 6.1:1 in both.
    render(
      <StockTakeItemCardHeader
        {...({
          itemId: "1",
          item: undefined,
          stockTakeItem: { item_name: "Rice", shelf_location: "A-01-03" },
          savedCount: null,
          discrepancy: null,
          isUnsaved: false,
          awaitingRecount: false,
        } as unknown as Props)}
      />,
    );

    const chip = screen.getByText("A-01-03");
    expect(chip.className).toContain("bg-surface-raised");
    expect(chip.className).toContain("text-on-secondary");
    expect(chip.className).not.toContain("text-on-muted");
  });
});
