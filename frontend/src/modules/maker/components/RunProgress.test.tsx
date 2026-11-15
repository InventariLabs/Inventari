import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RunPortions } from "./RunPortions";
import { RunSteps } from "./RunSteps";
import { ProductionStatusBadge } from "./ProductionStatusBadge";
import { todayIso } from "@/utils/formatters";
import type { ProductionOrder } from "@/modules/maker/types/maker";

const mocks = vi.hoisted(() => ({
  addPortion: vi.fn(),
  tickStep: vi.fn(),
}));

vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useAddPortion: () => ({ mutate: mocks.addPortion, isPending: false }),
  useTickStep: () => ({ mutate: mocks.tickStep, isPending: false }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const order = (over: Partial<ProductionOrder> = {}): ProductionOrder =>
  ({
    id: "ord-1",
    status: "IN_PROGRESS",
    planned_qty: "10",
    output_uom_symbol: "L",
    portions: [],
    steps: [],
    ...over,
  }) as unknown as ProductionOrder;

beforeEach(() => vi.clearAllMocks());

describe("RunPortions", () => {
  it("says nothing has been put on the shelf yet", () => {
    render(<RunPortions order={order()} canWrite />);
    expect(screen.getByText(/nothing has been put on the shelf/i)).toBeTruthy();
  });

  it("lists each portion with its day and batch", () => {
    render(
      <RunPortions
        order={order({
          portions: [
            {
              id: "p1",
              qty: "3",
              made_on: "2026-11-10",
              lot_name: "B1",
              created_at: "2026-11-10T10:00:00Z",
            },
          ],
        })}
        canWrite
      />,
    );
    expect(screen.getByText(/B1/)).toBeTruthy();
  });

  it("sends the portion with its batch and keeps the Add button off until there is a quantity", () => {
    render(<RunPortions order={order()} canWrite />);
    const add = screen.getByTestId("maker-portion-add-button");
    expect((add as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByTestId("maker-portion-qty-input"), {
      target: { value: "2.5" },
    });
    fireEvent.change(screen.getByTestId("maker-portion-lot-input"), {
      target: { value: " B2 " },
    });
    fireEvent.click(add);

    expect(mocks.addPortion).toHaveBeenCalledTimes(1);
    expect(mocks.addPortion.mock.calls[0][0]).toEqual({
      orderId: "ord-1",
      data: { qty: "2.5", made_on: todayIso(), output_lot_name: "B2" },
    });
  });

  it("offers no form to someone who cannot write", () => {
    render(<RunPortions order={order()} canWrite={false} />);
    expect(screen.queryByTestId("maker-portion-add-button")).toBeNull();
  });
});

describe("RunSteps", () => {
  const steps = [
    { text: "Rack", minutes: null, done_on: null },
    { text: "Filter", minutes: null, done_on: "2026-11-11" },
  ];

  it("ticks a step with today's day and clears it with null", () => {
    render(<RunSteps order={order({ steps })} canWrite />);

    fireEvent.click(screen.getByTestId("maker-step-0-checkbox"));
    expect(mocks.tickStep.mock.calls[0][0]).toEqual({
      orderId: "ord-1",
      index: 0,
      doneOn: todayIso(),
    });

    fireEvent.click(screen.getByTestId("maker-step-1-checkbox"));
    expect(mocks.tickStep.mock.calls[1][0]).toEqual({
      orderId: "ord-1",
      index: 1,
      doneOn: null,
    });
  });

  it("renders nothing for a formula with no steps", () => {
    const { container } = render(<RunSteps order={order()} canWrite />);
    expect(container.firstChild).toBeNull();
  });

  it("does not let a reader without write access tick", () => {
    render(<RunSteps order={order({ steps })} canWrite={false} />);
    expect(
      (screen.getByTestId("maker-step-0-checkbox") as HTMLInputElement)
        .disabled,
    ).toBe(true);
  });
});

describe("ProductionStatusBadge", () => {
  it("names a run in progress in its own words, not the raw status", () => {
    render(<ProductionStatusBadge status="IN_PROGRESS" />);
    expect(screen.getByText("In progress")).toBeTruthy();
  });
});
