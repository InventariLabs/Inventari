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

const period = planPeriod("week", new Date());
const [monday, tuesday, wednesday] = period.days;

function renderCalendar(canWrite: boolean) {
  return render(
    <MemoryRouter>
      <PlanCalendar
        period={period}
        canWrite={canWrite}
        orders={[order("a", monday, "covered"), order("b", tuesday, "partial")]}
      />
    </MemoryRouter>,
  );
}

describe("PlanCalendar", () => {
  beforeEach(() => mutate.mockReset());

  it("lays the week out by day with each run's coverage", () => {
    renderCalendar(true);
    const firstDay = screen.getByTestId(`maker-plan-day-${monday}`);
    expect(within(firstDay).getByText("Bread a")).toBeInTheDocument();
    expect(within(firstDay).getByText("Covered")).toBeInTheDocument();
    const secondDay = screen.getByTestId(`maker-plan-day-${tuesday}`);
    expect(within(secondDay).getByText("Partly covered")).toBeInTheDocument();
  });

  it("hides the empty days from a phone, which reads the grid as a list by day", () => {
    renderCalendar(true);
    expect(
      screen.getByTestId(`maker-plan-day-${wednesday}`).className,
    ).toContain("hidden md:block");
    expect(
      screen.getByTestId(`maker-plan-day-${monday}`).className,
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
