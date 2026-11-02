import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import {
  CompositionBar,
  CompositionLegend,
  CompositionRow,
  compositionBarGeometry,
  SEGMENT_MIN_PX,
} from "@/components/ui/CompositionBar";

describe("compositionBarGeometry", () => {
  it("makes the fill proportional to the row's share of the largest row", () => {
    const big = compositionBarGeometry(52, 52, [{ key: "ok", count: 52 }]);
    const small = compositionBarGeometry(6, 52, [{ key: "ok", count: 6 }]);
    expect(big.fillPercent).toBe(100);
    expect(small.fillPercent).toBeCloseTo((6 / 52) * 100, 5);
  });

  it("gives each segment a share proportional to its count", () => {
    const g = compositionBarGeometry(24, 52, [
      { key: "bad", count: 1 },
      { key: "warn", count: 3 },
      { key: "ok", count: 20 },
    ]);
    expect(g.segments.map((s) => [s.key, s.grow])).toEqual([
      ["bad", 1],
      ["warn", 3],
      ["ok", 20],
    ]);
  });

  it("keeps every non-empty segment at least the minimum width", () => {
    const g = compositionBarGeometry(412, 412, [
      { key: "bad", count: 1 },
      { key: "ok", count: 411 },
    ]);
    expect(SEGMENT_MIN_PX).toBe(4);
    expect(g.segments.every((s) => s.minWidthPx === SEGMENT_MIN_PX)).toBe(true);
  });

  it("drops empty segments instead of drawing a zero-width sliver", () => {
    const g = compositionBarGeometry(10, 10, [
      { key: "bad", count: 0 },
      { key: "ok", count: 10 },
    ]);
    expect(g.segments.map((s) => s.key)).toEqual(["ok"]);
  });

  it("widens a tiny fill so the segment minimums still fit inside it", () => {
    // 7 of 412 is 1.7% — about ten pixels on a phone, less than three
    // four-pixel segments need. The fill grows to hold them rather than the
    // segments spilling past it.
    const g = compositionBarGeometry(7, 412, [
      { key: "bad", count: 1 },
      { key: "warn", count: 1 },
      { key: "ok", count: 5 },
    ]);
    expect(g.fillPercent).toBeCloseTo((7 / 412) * 100, 5);
    expect(g.fillMinWidthPx).toBe(3 * SEGMENT_MIN_PX);
  });

  it("draws no fill for an empty row", () => {
    const g = compositionBarGeometry(0, 52, [{ key: "ok", count: 0 }]);
    expect(g.fillPercent).toBe(0);
    expect(g.fillMinWidthPx).toBe(0);
    expect(g.segments).toEqual([]);
  });

  it("does not divide by zero when every row is empty", () => {
    const g = compositionBarGeometry(0, 0, []);
    expect(g.fillPercent).toBe(0);
  });
});

describe("CompositionBar", () => {
  it("is an image whose name carries the numbers, not the colours", () => {
    render(
      <CompositionBar
        count={58}
        maxCount={58}
        segments={[
          { key: "warn", count: 4, tone: "warning" },
          { key: "bad", count: 1, tone: "danger" },
          { key: "ok", count: 53, tone: "ok" },
        ]}
        ariaLabel="58 items: 4 expiring, 1 expired"
      />,
    );
    const bar = screen.getByRole("img", {
      name: "58 items: 4 expiring, 1 expired",
    });
    expect(bar).toBeInTheDocument();
  });

  it("renders one element per non-empty segment, in the given order", () => {
    const { container } = render(
      <CompositionBar
        count={24}
        maxCount={52}
        segments={[
          { key: "bad", count: 1, tone: "danger" },
          { key: "low", count: 0, tone: "info" },
          { key: "ok", count: 23, tone: "ok" },
        ]}
        ariaLabel="24"
      />,
    );
    const segs = container.querySelectorAll("[data-segment]");
    expect([...segs].map((s) => s.getAttribute("data-segment"))).toEqual([
      "bad",
      "ok",
    ]);
    expect((segs[0] as HTMLElement).style.flexGrow).toBe("1");
    expect((segs[1] as HTMLElement).style.flexGrow).toBe("23");
    expect((segs[0] as HTMLElement).style.minWidth).toBe("4px");
  });

  it("sizes the fill from the row's share and the segments' minimums", () => {
    const { container } = render(
      <CompositionBar
        count={7}
        maxCount={412}
        segments={[
          { key: "bad", count: 1, tone: "danger" },
          { key: "ok", count: 6, tone: "ok" },
        ]}
        ariaLabel="7"
      />,
    );
    const fill = container.querySelector("[data-fill]") as HTMLElement;
    expect(parseFloat(fill.style.width)).toBeCloseTo((7 / 412) * 100, 3);
    expect(fill.style.minWidth).toBe("8px");
  });

  it("renders an empty track for an empty row", () => {
    const { container } = render(
      <CompositionBar count={0} maxCount={52} segments={[]} ariaLabel="0" />,
    );
    expect(container.querySelector("[data-fill]")).toBeNull();
    expect(screen.getByRole("img", { name: "0" })).toBeInTheDocument();
  });
});

describe("CompositionLegend", () => {
  const entries = [
    { key: "ok", tone: "ok", label: "In order" },
    { key: "warn", tone: "warning", label: "Expiring" },
    { key: "bad", tone: "danger", label: "Expired" },
    { key: "low", tone: "info", label: "Low stock" },
  ] as const;

  it("lists only the colours that appear in the bars", () => {
    render(
      <CompositionLegend
        entries={[...entries]}
        bars={[
          [
            { key: "ok", count: 10 },
            { key: "warn", count: 2 },
          ],
          [
            { key: "ok", count: 5 },
            { key: "bad", count: 0 },
          ],
        ]}
      />,
    );
    expect(screen.getByText("In order")).toBeInTheDocument();
    expect(screen.getByText("Expiring")).toBeInTheDocument();
    expect(screen.queryByText("Expired")).toBeNull();
    expect(screen.queryByText("Low stock")).toBeNull();
  });

  it("renders nothing when no bar has a segment", () => {
    const { container } = render(
      <CompositionLegend entries={[...entries]} bars={[[]]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("CompositionRow", () => {
  function renderRow(props: Partial<Parameters<typeof CompositionRow>[0]>) {
    return render(
      <MemoryRouter>
        <ul>
          <CompositionRow
            icon="Package"
            name="Laptops"
            count={18}
            maxCount={18}
            segments={[
              { key: "issued", count: 11, tone: "active" },
              { key: "ok", count: 7, tone: "ok" },
            ]}
            ariaLabel="18 assets: 11 issued"
            {...props}
          />
        </ul>
      </MemoryRouter>,
    );
  }

  it("leads from the name to the row's page when it has one", () => {
    renderRow({ href: "/equipment/assets?category=c1" });
    expect(screen.getByRole("link", { name: "Laptops" })).toHaveAttribute(
      "href",
      "/equipment/assets?category=c1",
    );
  });

  it("names the row without a link when it has no page", () => {
    renderRow({});
    expect(screen.getByText("Laptops")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("draws the bar with its sentence, the meta and the count", () => {
    const { container } = renderRow({ meta: "11 issued" });
    expect(
      screen.getByRole("img", { name: "18 assets: 11 issued" }),
    ).toBeInTheDocument();
    expect(screen.getByText("11 issued")).toBeInTheDocument();
    expect(screen.getByText("18")).toBeInTheDocument();
    expect(
      container.querySelector('[data-segment="issued"]')?.className,
    ).toContain("bg-bar-active");
  });

  it("keeps an empty track for a row of zero, with nothing to announce", () => {
    const { container } = renderRow({ count: 0, segments: [] });
    expect(screen.queryByRole("img")).toBeNull();
    expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull();
    expect(screen.getByText("0")).toBeInTheDocument();
  });
});
