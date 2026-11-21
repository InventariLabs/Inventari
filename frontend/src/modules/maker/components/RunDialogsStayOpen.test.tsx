import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@/test/utils";
import { FinishRunAction } from "@/modules/maker/components/FinishRunAction";
import { ReverseRunAction } from "@/modules/maker/components/ReverseRunAction";
import type { ProductionOrder } from "@/modules/maker/types/maker";

const mocks = vi.hoisted(() => ({
  finish: vi.fn(),
  reverse: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess, error: mocks.toastError },
}));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));
vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useFinishProduction: () => ({
    mutateAsync: mocks.finish,
    isPending: false,
  }),
  useReverseProduction: () => ({
    mutateAsync: mocks.reverse,
    isPending: false,
  }),
}));

const run = {
  id: "ord-1",
  status: "IN_PROGRESS",
  planned_qty: "10",
  output_uom_symbol: "kg",
  shelf_life_days: null,
} as unknown as ProductionOrder;

/** The refusal the server sends: a 4xx whose detail is a sentence for a person. */
function refusal(detail: string) {
  return Object.assign(new Error("refused"), {
    isAxiosError: true,
    response: { status: 400, data: { detail } },
  });
}

describe("a run's dialogs on a refusal", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps the finish dialog open, with the refusal and the quantity typed", async () => {
    mocks.finish.mockRejectedValueOnce(
      refusal("The run has already put 7 kg on the shelf."),
    );
    render(<FinishRunAction order={run} />);

    fireEvent.click(screen.getByTestId("maker-detail-finish-button"));
    fireEvent.change(screen.getByTestId("maker-finish-actual-qty-input"), {
      target: { value: "5" },
    });
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Finish run",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The run has already put 7 kg on the shelf.",
    );
    expect(screen.getByTestId("maker-finish-actual-qty-input")).toHaveValue(5);
    expect(mocks.toastSuccess).not.toHaveBeenCalled();
  });

  it("closes the finish dialog once the server accepts the quantity", async () => {
    mocks.finish.mockResolvedValueOnce({});
    render(<FinishRunAction order={run} />);

    fireEvent.click(screen.getByTestId("maker-detail-finish-button"));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Finish run",
      }),
    );

    await waitFor(() =>
      expect(screen.queryByTestId("maker-finish-actual-qty-input")).toBeNull(),
    );
    expect(mocks.toastSuccess).toHaveBeenCalled();
  });

  it("keeps the undo dialog open with the reason it was refused", async () => {
    mocks.reverse.mockRejectedValueOnce(
      refusal("Some of what it made has already left its location."),
    );
    render(
      <ReverseRunAction
        order={{ ...run, status: "COMPLETED" } as ProductionOrder}
      />,
    );

    fireEvent.click(screen.getByTestId("maker-detail-reverse-button"));
    fireEvent.click(screen.getByRole("button", { name: "Yes, undo run" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Some of what it made has already left its location.",
    );
  });
});
