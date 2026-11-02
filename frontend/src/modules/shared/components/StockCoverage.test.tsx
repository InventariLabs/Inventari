import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StockCoverage, toneForCoverage } from "./StockCoverage";

describe("toneForCoverage", () => {
  it("separates all, some and none", () => {
    expect(toneForCoverage(5, 5)).toBe("ok");
    expect(toneForCoverage(4, 5)).toBe("partial");
    expect(toneForCoverage(0, 5)).toBe("none");
  });

  it("does not call an empty requirement satisfied", () => {
    // 0/0 would read as "everything is here" on a recipe with no
    // ingredients to check; the callers hide the badge instead.
    expect(toneForCoverage(0, 0)).toBe("none");
  });
});

describe("StockCoverage", () => {
  it("writes the ratio and says what it means", () => {
    render(<StockCoverage available={4} total={5} />);

    expect(screen.getByText("4/5 in stock")).toBeInTheDocument();
    expect(screen.getByText("4 of 5 in stock")).toBeInTheDocument();
  });

  it("spells the ratio out for a reader who cannot see it", () => {
    // The card used to carry the meaning in a `title`, which a touch screen
    // never opens; "4/5" alone sat in a row of numbers next to "30 min".
    const { container } = render(<StockCoverage available={4} total={5} />);

    expect(container.querySelector(".sr-only")).toHaveTextContent(
      "4 of 5 in stock",
    );
    expect(screen.getByText("4/5 in stock")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  it("names the lines it could not count instead of reading them as missing", () => {
    // An ingredient whose measure cannot meet the shelf's used to
    // count as "have" on the card. Not counted in — and not read as an
    // empty shelf either: "0/1 in stock" alone would be the same lie told
    // the other way round.
    render(<StockCoverage available={0} total={1} incomparable={1} />);

    expect(screen.getByText("0/1 in stock")).toBeInTheDocument();
    expect(
      screen.getByText("cannot count 1 of the 1 needed"),
    ).toBeInTheDocument();
  });
});
