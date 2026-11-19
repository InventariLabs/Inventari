import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { addDays, format } from "date-fns";
import { MemoryRouter } from "react-router-dom";
import { FinishRunAction } from "./FinishRunAction";
import { StartRunAction } from "./StartRunAction";
import { todayIso } from "@/utils/formatters";
import type { ProductionOrder } from "@/modules/maker/types/maker";

const mocks = vi.hoisted(() => ({
  start: vi.fn(),
  finish: vi.fn(),
  batches: {
    payload: [] as { template_id: string; lot_id: string; quantity: string }[],
    short: new Set<string>(),
  },
}));

// The plan the server makes is not the subject here: what the dialog does
// with the choice is.
vi.mock("@/modules/maker/hooks/useBatchChoice", () => ({
  useBatchChoice: () => ({
    plans: [],
    choices: {},
    choose: vi.fn(),
    short: mocks.batches.short,
    payload: mocks.batches.payload,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useStartProduction: () => ({ mutate: mocks.start, isPending: false }),
  useFinishProduction: () => ({ mutate: mocks.finish, isPending: false }),
}));

vi.mock("@/hooks/useActiveProfile", () => ({
  useActiveProfile: () => null,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const order = {
  id: "ord-1",
  planned_qty: "10",
  output_uom_symbol: "L",
} as unknown as ProductionOrder;

beforeEach(() => {
  vi.clearAllMocks();
  mocks.batches.payload = [];
  mocks.batches.short = new Set();
});

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
      data: { started_on: todayIso(), ingredient_lots: undefined },
    });
  });

  it("starts the run on the batches the person chose", () => {
    const chosen = { template_id: "t1", lot_id: "lot-9", quantity: "6" };
    mocks.batches.payload = [chosen];
    render(
      <MemoryRouter>
        <StartRunAction order={order} onShortage={vi.fn()} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("maker-detail-start-button"));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Start run",
      }),
    );

    expect(mocks.start.mock.calls[0][0].data.ingredient_lots).toEqual([chosen]);
  });

  it("will not start while a chosen batch cannot give what the run needs", () => {
    mocks.batches.short = new Set(["t1"]);
    render(
      <MemoryRouter>
        <StartRunAction order={order} onShortage={vi.fn()} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("maker-detail-start-button"));

    const start = within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Start run",
    });
    expect((start as HTMLButtonElement).disabled).toBe(true);
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
        best_before: undefined,
      },
    });
  });

  it("dates the closing quantity from the product's shelf life, as the server would", () => {
    render(
      <FinishRunAction
        order={{ ...order, shelf_life_days: 30 } as ProductionOrder}
      />,
    );
    fireEvent.click(screen.getByTestId("maker-detail-finish-button"));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Finish run",
      }),
    );

    expect(mocks.finish.mock.calls[0][0].data.best_before).toBe(
      format(addDays(new Date(), 30), "yyyy-MM-dd"),
    );
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

  it("opens on empty fields after a refused finish", () => {
    render(<FinishRunAction order={order} />);
    fireEvent.click(screen.getByTestId("maker-detail-finish-button"));
    fireEvent.change(screen.getByTestId("maker-finish-actual-qty-input"), {
      target: { value: "5" },
    });
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Finish run",
      }),
    );
    mocks.finish.mock.calls[0][1].onError(new Error("refused"));

    fireEvent.click(screen.getByTestId("maker-detail-finish-button"));
    expect(
      (screen.getByTestId("maker-finish-actual-qty-input") as HTMLInputElement)
        .value,
    ).toBe("");
  });

  it("asks before closing far above the plan, naming the extra quantity", () => {
    render(<FinishRunAction order={order} />);
    fireEvent.click(screen.getByTestId("maker-detail-finish-button"));
    fireEvent.change(screen.getByTestId("maker-finish-actual-qty-input"), {
      target: { value: "59" },
    });
    const dialog = screen.getByRole("alertdialog");
    const finishButton = within(dialog).getByRole("button", {
      name: "Finish run",
    }) as HTMLButtonElement;

    const notice = screen.getByTestId("maker-overproduction-notice");
    expect(notice.textContent).toContain("49");
    expect(notice.textContent).toContain("ingredients stay as planned");
    expect(finishButton.disabled).toBe(true);

    fireEvent.click(screen.getByTestId("maker-overproduction-confirm"));
    expect(finishButton.disabled).toBe(false);
    fireEvent.click(finishButton);
    expect(mocks.finish.mock.calls[0][0].data.actual_qty).toBe("59");
  });

  it("does not ask for a quantity within a quarter of the plan", () => {
    render(<FinishRunAction order={order} />);
    fireEvent.click(screen.getByTestId("maker-detail-finish-button"));
    fireEvent.change(screen.getByTestId("maker-finish-actual-qty-input"), {
      target: { value: "12" },
    });

    expect(screen.queryByTestId("maker-overproduction-notice")).toBeNull();
  });
});
