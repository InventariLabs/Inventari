import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProductionCoverageBadge } from "./ProductionCoverageBadge";

describe("ProductionCoverageBadge", () => {
  it.each([
    ["covered", "Covered"],
    ["partial", "Partly covered"],
    ["short", "Short"],
  ] as const)("names a %s run", (coverage, label) => {
    render(<ProductionCoverageBadge coverage={coverage} />);
    expect(screen.getByTestId("maker-order-coverage")).toHaveTextContent(label);
  });

  it("says nothing about a run past the draft", () => {
    const { container } = render(<ProductionCoverageBadge coverage={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
