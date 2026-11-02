import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { YieldLossNote } from "@/modules/maker/components/YieldLossNote";

/**
 * The sign is the whole point. `effective_qty = qty_per_batch *
 * (1 + yield_loss_pct / 100)`, so the annotation has to read as "more is
 * consumed"; the tree editor used to render `(-10%)`, telling the opposite
 * story about the same line.
 */
describe("YieldLossNote", () => {
  it("annotates a loss as extra consumption, never as a reduction", () => {
    render(<YieldLossNote pct="10" />);
    expect(screen.getByText("+10%")).toBeInTheDocument();
  });

  it("trims the trailing zeros the API sends on decimals", () => {
    render(<YieldLossNote pct="7.50" />);
    expect(screen.getByText("+7.5%")).toBeInTheDocument();
  });

  it.each([["0"], ["0.00"], [null], [undefined], [""]])(
    "renders nothing for %s",
    (pct) => {
      const { container } = render(<YieldLossNote pct={pct} />);
      expect(container).toBeEmptyDOMElement();
    },
  );
});
