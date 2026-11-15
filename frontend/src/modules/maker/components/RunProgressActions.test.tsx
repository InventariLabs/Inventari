import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { FinishRunAction } from "./FinishRunAction";
import { StartRunAction } from "./StartRunAction";
import { todayIso } from "@/utils/formatters";
import type { ProductionOrder } from "@/modules/maker/types/maker";

const mocks = vi.hoisted(() => ({ start: vi.fn(), finish: vi.fn() }));

vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useStartProduction: () => ({ mutate: mocks.start, isPending: false }),
  useFinishProduction: () => ({ mutate: mocks.finish, isPending: false }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const order = {
  id: "ord-1",
  planned_qty: "10",
  output_uom_symbol: "L",
} as unknown as ProductionOrder;

beforeEach(() => vi.clearAllMocks());

describe("StartRunAction", () => {
  it("asks for the day, then starts the run on it", () => {
    render(
      <MemoryRouter>
        <StartRunAction order={order} onShortage={vi.fn()} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("maker-detail-start-button"));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Start run" }));

    expect(mocks.start.mock.calls[0][0]).toEqual({
      orderId: "ord-1",
      data: { started_on: todayIso() },
    });
  });

  it("hands a shortage refusal to the page's own dialog", () => {
    const onShortage = vi.fn();
    render(
      <MemoryRouter>
        <StartRunAction order={order} onShortage={onShortage} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("maker-detail-start-button"));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Start run",
      }),
    );
    const refusal = {
      response: {
        data: {
          detail: {
            error: "insufficient_stock",
            shortages: [{ child_template_id: "t1" }],
            short_at_create: true,
          },
        },
      },
    };
    mocks.start.mock.calls[0][1].onError(refusal);

    expect(onShortage).toHaveBeenCalledWith(
      [{ child_template_id: "t1" }],
      true,
    );
  });
});

describe("FinishRunAction", () => {
  it("finishes with what the whole run made and the day it closed", () => {
    render(<FinishRunAction order={order} />);
    fireEvent.click(screen.getByTestId("maker-detail-finish-button"));
    fireEvent.change(screen.getByTestId("maker-finish-actual-qty-input"), {
      target: { value: "9" },
    });
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Finish run",
      }),
    );

    expect(mocks.finish.mock.calls[0][0]).toEqual({
      orderId: "ord-1",
      data: {
        actual_qty: "9",
        finished_on: todayIso(),
        output_lot_name: undefined,
      },
    });
  });

  it("leaves the quantity out when none is typed, so the server uses the plan", () => {
    render(<FinishRunAction order={order} />);
    fireEvent.click(screen.getByTestId("maker-detail-finish-button"));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Finish run",
      }),
    );

    expect(mocks.finish.mock.calls[0][0].data.actual_qty).toBeUndefined();
  });
});
