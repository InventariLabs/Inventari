import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { PlanCalendar } from "./PlanCalendar";
import { planPeriod } from "@/modules/maker/lib/planPeriod";
import type { ProductionOrder } from "@/modules/maker/types/maker";

const mutate = vi.fn();
vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useUpdateProductionOrder: () => ({ mutate, isPending: false }),
}));

const order = (id: string, day: string, coverage: "covered" | "partial") =>
  ({
    id,
    number: id,
    output_template_name: `Bread ${id}`,
    planned_qty: "6",
    output_uom_symbol: null,
    production_date: day,
    status: "DRAFT",
    coverage,
  }) as unknown as ProductionOrder;

const period = planPeriod("week", new Date("2031-03-05T12:00:00"));

function renderCalendar(canWrite: boolean) {
  return render(
    <MemoryRouter>
      <PlanCalendar
        period={period}
        canWrite={canWrite}
        orders={[
          order("a", "2031-03-03", "covered"),
          order("b", "2031-03-04", "partial"),
        ]}
      />
    </MemoryRouter>,
  );
}

describe("PlanCalendar", () => {
  beforeEach(() => mutate.mockReset());

  it("lays the week out by day with each run's coverage", () => {
    renderCalendar(true);
    const monday = screen.getByTestId("maker-plan-day-2031-03-03");
    expect(within(monday).getByText("Bread a")).toBeInTheDocument();
    expect(within(monday).getByText("Covered")).toBeInTheDocument();
    const tuesday = screen.getByTestId("maker-plan-day-2031-03-04");
    expect(within(tuesday).getByText("Partly covered")).toBeInTheDocument();
  });

  it("hides the empty days from a phone, which reads the grid as a list by day", () => {
    renderCalendar(true);
    expect(screen.getByTestId("maker-plan-day-2031-03-05").className).toContain(
      "hidden md:block",
    );
    expect(
      screen.getByTestId("maker-plan-day-2031-03-03").className,
    ).not.toContain("hidden");
  });

  it("moves a run to another day from the calendar", async () => {
    renderCalendar(true);
    await userEvent.click(
      screen.getByRole("button", { name: "Move Bread a to another day" }),
    );
    expect(screen.getByText("Planned for", { exact: false })).toBeVisible();
  });

  it("offers no move to an account that cannot write", () => {
    renderCalendar(false);
    expect(screen.queryByText("Move")).not.toBeInTheDocument();
  });
});
