import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MakerResultWidget } from "./MakerResultWidget";

const organizationCurrency = { value: "USD" as string | undefined };

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => organizationCurrency.value,
}));

interface MonthRow {
  month: string;
  result: string;
  orders: number;
  overproduced_orders?: number;
}

const WITH_RESULTS: MonthRow[] = [
  { month: "2026-03", result: "10.00", orders: 1 },
  { month: "2026-04", result: "-5.00", orders: 1 },
  { month: "2026-05", result: "0.00", orders: 0 },
  { month: "2026-06", result: "25.00", orders: 2 },
  { month: "2026-07", result: "0.00", orders: 0 },
  { month: "2026-08", result: "40.50", orders: 3 },
];

/** What a fresh organization gets: the six buckets the service always builds. */
const NOTHING_CLOSED: MonthRow[] = WITH_RESULTS.map(({ month }) => ({
  month,
  result: "0.00",
  orders: 0,
}));

const monthly = { rows: WITH_RESULTS };

vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useMakerMonthlyResult: () => ({ data: monthly.rows, isLoading: false }),
}));

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerSettings: () => ({
    data: { reference_direction: "SAVINGS" },
  }),
}));

function renderWidget() {
  return render(
    <MemoryRouter>
      <MakerResultWidget />
    </MemoryRouter>,
  );
}

describe("MakerResultWidget", () => {
  it("shows the title and the latest month as the headline", () => {
    renderWidget();
    expect(screen.getByText("Savings vs shop price by month")).toBeTruthy();
    expect(screen.getByText("August")).toBeTruthy();
    expect(screen.getByText("$40.50")).toBeTruthy();
  });

  it("lists the previous months with their values", () => {
    renderWidget();
    expect(screen.getByText("July")).toBeTruthy();
    expect(screen.getByText("June")).toBeTruthy();
    expect(screen.getByText("$25.00")).toBeTruthy();
    expect(screen.getByText("May")).toBeTruthy();
    expect(screen.getAllByText("$0.00").length).toBeGreaterThan(0);
  });

  it("marks the amounts unsigned when the organization set no currency", () => {
    // A figure labelled PLN whatever the organization trades in would pass
    // for a real one, so with no currency set the amounts carry no sign.
    organizationCurrency.value = undefined;
    try {
      renderWidget();
      expect(screen.getByText("40.50 ?")).toBeTruthy();
    } finally {
      organizationCurrency.value = "USD";
    }
  });

  it("shows the run count for the latest month", () => {
    renderWidget();
    expect(screen.getByText(/3 runs/)).toBeTruthy();
  });

  it("says nothing has been closed instead of printing six zeros", () => {
    // The service builds six buckets whatever happened, so the old
    // `months.length <= 1` guard never fired and a fresh organization read
    // six rows of "$0.00" in the largest block on the dashboard.
    monthly.rows = NOTHING_CLOSED;
    try {
      renderWidget();
      expect(
        screen.getByText(
          "Nothing to show yet: a run gets a result when it is completed while its BOM has a sale price and every ingredient has a cost.",
        ),
      ).toBeTruthy();
      expect(screen.queryByText("$0.00")).toBeNull();
    } finally {
      monthly.rows = WITH_RESULTS;
    }
  });

  it("keeps the semantic colour off a zero", () => {
    monthly.rows = [{ month: "2026-08", result: "0.00", orders: 2 }];
    try {
      renderWidget();
      const headline = screen.getByText("$0.00");
      expect(headline.className).not.toMatch(/text-accent|text-red/);
    } finally {
      monthly.rows = WITH_RESULTS;
    }
  });

  it("traces the definition back to the setting that chose the word", () => {
    renderWidget();
    expect(
      screen.getByRole("link", {
        name: "Shop price minus the cost to make it",
      }),
    ).toHaveAttribute("href", "/maker/settings");
  });

  it("says when a month's result counts runs that closed above their plan", () => {
    monthly.rows = [
      { month: "2026-07", result: "5.00", orders: 1, overproduced_orders: 1 },
      { month: "2026-08", result: "40.50", orders: 3, overproduced_orders: 2 },
    ];
    try {
      renderWidget();
      const notes = screen.getAllByTestId("maker-result-overproduced");
      expect(notes).toHaveLength(2);
      expect(notes[0].textContent).toContain("2 runs closed above their plan");
    } finally {
      monthly.rows = WITH_RESULTS;
    }
  });

  it("stays quiet when no run closed above its plan", () => {
    renderWidget();
    expect(screen.queryByTestId("maker-result-overproduced")).toBeNull();
  });
});
