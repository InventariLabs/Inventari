import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CostFigure, CostGapNote } from "./CostFigure";

vi.mock("@/hooks/useMoney", () => ({
  useMoney: () => (value: string | number | null) =>
    value === null ? "—" : `${Number(value).toFixed(2)} zł`,
}));

describe("CostFigure", () => {
  it("shows the amount when every ingredient carried a rate", () => {
    render(<CostFigure value="12.50" priced={3} unpriced={0} />);

    expect(screen.getByText("12.50 zł")).toBeInTheDocument();
  });

  it("refuses a number when not one ingredient carried a rate", () => {
    // Measured on the recipe cost tab: the ingredient row read "—" and the
    // Total right under it read "$0.00". Unpriced ingredients contribute
    // zero so the sum can finish, and the sum was printed as a measurement.
    render(<CostFigure value="0.00" priced={0} unpriced={2} />);

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/0\.00/)).toBeNull();
  });

  it("keeps a partial amount and says what it leaves out", () => {
    render(<CostFigure value="4.00" priced={2} unpriced={1} />);

    expect(screen.getByText("4.00 zł")).toBeInTheDocument();
    expect(
      screen.getByText(
        "1 ingredient has no rate, so it is missing from this figure.",
      ),
    ).toBeInTheDocument();
  });

  it("states a genuine zero from a fully priced formula", () => {
    // Every ingredient priced at nothing is a measurement, not a gap.
    render(<CostFigure value="0.00" priced={2} unpriced={0} />);

    expect(screen.getByText("0.00 zł")).toBeInTheDocument();
    expect(screen.queryByText("—")).toBeNull();
  });

  it("says nothing was computed when there is no value at all", () => {
    render(<CostFigure value={null} priced={0} unpriced={0} />);

    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("carries a caller's own sentence instead of the general one", () => {
    render(
      <CostFigure value="0.00" priced={0} unpriced={1} note="Nobody knows." />,
    );

    expect(screen.getByText("Nobody knows.")).toBeInTheDocument();
  });

  it("stays out of the accessibility tree when the caller prints the sentence visibly", () => {
    // The production preview and the cost tab render the gap sentence in an
    // amber card / CostGapNote next to the figure; an sr-only copy here made
    // a screen reader say the same sentence twice.
    render(
      <CostFigure value="4.00" priced={2} unpriced={1} announce={false} />,
    );

    expect(screen.getByText("4.00 z\u0142")).toBeInTheDocument();
    expect(
      screen.queryByText(
        "1 ingredient has no rate, so it is missing from this figure.",
      ),
    ).toBeNull();
  });

  it("links the figure to the visible sentence the caller prints", () => {
    // The old title kept a reader association but was hover-only — a touch
    // screen never opens it and readers announce it inconsistently. An
    // aria-describedby pointing at the visible note is announced as the
    // figure's own description: same association, nothing repeated.
    render(
      <>
        <CostFigure
          value="4.00"
          priced={2}
          unpriced={1}
          announce={false}
          describedBy="cost-gap-note"
        />
        <CostGapNote priced={2} unpriced={1} id="cost-gap-note" />
      </>,
    );

    const figure = screen.getByText("4.00 z\u0142").closest("span");
    expect(figure).toHaveAttribute("aria-describedby", "cost-gap-note");
    expect(screen.getByText(/1 ingredient has no rate/)).toHaveAttribute(
      "id",
      "cost-gap-note",
    );
  });

  it("points the refused dash at the sentence that explains it", () => {
    render(
      <CostFigure
        value={null}
        priced={0}
        unpriced={2}
        announce={false}
        describedBy="why-no-figure"
      />,
    );

    expect(screen.getByText("—")).toHaveAttribute(
      "aria-describedby",
      "why-no-figure",
    );
  });

  it("names no description when nothing is missing and the note renders null", () => {
    // A recipe without ingredients: no value and nothing unpriced. The
    // caller's note renders null, so a describedby here would point at an
    // element that is not in the page — the dangling reference the title
    // used to be, one level down.
    render(
      <CostFigure
        value={null}
        priced={0}
        unpriced={0}
        announce={false}
        describedBy="cost-gap-note-that-is-not-there"
      />,
    );

    expect(screen.getByText("—")).not.toHaveAttribute("aria-describedby");
  });

  it("carries no description reference when the caller names none", () => {
    render(<CostFigure value="4.00" priced={2} unpriced={1} />);

    expect(
      screen.getByText("4.00 z\u0142").closest("span"),
    ).not.toHaveAttribute("aria-describedby");
  });
});

describe("CostGapNote", () => {
  it("names how many ingredients the figure is missing", () => {
    render(<CostGapNote priced={2} unpriced={3} />);

    expect(
      screen.getByText(
        "3 ingredients have no rate, so they are missing from this figure.",
      ),
    ).toBeInTheDocument();
  });

  it("explains a refused figure by counting what has no rate", () => {
    render(<CostGapNote priced={0} unpriced={2} />);

    expect(
      screen.getByText(
        "No rate for any of the 2 ingredients — there is nothing to add up.",
      ),
    ).toBeInTheDocument();
  });

  it("stays out of the way when nothing is missing", () => {
    const { container } = render(<CostGapNote priced={3} unpriced={0} />);

    expect(container).toBeEmptyDOMElement();
  });
});
