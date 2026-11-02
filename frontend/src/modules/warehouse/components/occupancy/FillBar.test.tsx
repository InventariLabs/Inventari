import { describe, expect, it } from "vitest";
import { render, screen } from "@/test/utils";
import { cell, entry } from "@/test/factories/occupancy";
import { FillBar } from "./FillBar";

describe("FillBar", () => {
  it("makes one segment per limited product, whose widths are their shares", () => {
    const { container } = render(
      <FillBar
        cell={cell("A", "Shelf A", [
          entry("Rice", "20", "100"),
          entry("Plums", "10", "40"),
        ])}
      />,
    );

    const segments = container.querySelectorAll("[role=meter] > span");
    expect([...segments].map((s) => (s as HTMLElement).style.width)).toEqual([
      "20%",
      "25%",
    ]);
    expect(screen.getByText("45%")).toBeInTheDocument();
  });

  it("keeps the proportions and fills the bar when the shelf is over its limit", () => {
    const { container } = render(
      <FillBar
        cell={cell("A", "Shelf A", [
          entry("Rice", "100", "100"),
          entry("Plums", "50", "100"),
        ])}
      />,
    );

    const widths = [...container.querySelectorAll("[role=meter] > span")].map(
      (s) => Number.parseFloat((s as HTMLElement).style.width),
    );
    expect(widths[0] + widths[1]).toBeCloseTo(100);
    expect(screen.getByText("150%")).toBeInTheDocument();
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "100");
  });

  it("says Empty, not 0%, for a limited location with nothing on it", () => {
    render(
      <FillBar cell={cell("A", "Shelf A", [entry("Rice", "0", "100")])} />,
    );

    expect(screen.getByText("Empty")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("draws no bar where nobody set a limit", () => {
    render(
      <FillBar cell={cell("A", "Shelf A", [entry("Flour", "30", null)])} />,
    );

    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(screen.getByText("No limit")).toBeInTheDocument();
  });
});
