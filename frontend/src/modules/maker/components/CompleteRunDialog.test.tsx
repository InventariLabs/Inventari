import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { CompleteRunDialog } from "./CompleteRunDialog";
import { useCompleteRun } from "@/modules/maker/hooks/useCompleteRun";
import type { ProductionOrder } from "@/modules/maker/types/maker";

const mocks = vi.hoisted(() => ({ complete: vi.fn() }));

vi.mock("@/modules/maker/hooks/useBatchChoice", () => ({
  useBatchChoice: () => ({
    plans: [],
    choices: {},
    choose: vi.fn(),
    short: new Set<string>(),
    payload: [],
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useCompleteProduction: () => ({
    mutateAsync: mocks.complete,
    isPending: false,
  }),
}));

vi.mock("@/hooks/useActiveProfile", () => ({
  useActiveProfile: () => null,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const order = {
  id: "ord-1",
  status: "DRAFT",
  planned_qty: "10",
  output_uom_symbol: "L",
} as unknown as ProductionOrder;

/** The dialog wired to the hook the order page wires it to. */
function Harness() {
  const run = useCompleteRun(order);
  return (
    <>
      <button onClick={() => run.setShowConfirm(true)}>open</button>
      <CompleteRunDialog order={order} run={run} bomIsEmpty={false} />
    </>
  );
}

function openDialog() {
  render(
    <MemoryRouter>
      <Harness />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByText("open"));
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.complete.mockResolvedValue({});
});

describe("CompleteRunDialog overproduction", () => {
  it("asks before closing far above the plan, then lets the run close", async () => {
    openDialog();
    fireEvent.change(screen.getByTestId("maker-complete-actual-qty-input"), {
      target: { value: "59" },
    });
    const dialog = screen.getByRole("alertdialog");
    const complete = within(dialog).getByRole("button", {
      name: "Complete run",
    }) as HTMLButtonElement;

    const notice = screen.getByTestId("maker-overproduction-notice");
    expect(notice.textContent).toContain("49");
    expect(complete.disabled).toBe(true);

    fireEvent.click(screen.getByTestId("maker-overproduction-confirm"));
    expect(complete.disabled).toBe(false);
    await act(async () => {
      fireEvent.click(complete);
    });
    expect(mocks.complete.mock.calls[0][0].data.actual_qty).toBe("59");
  });

  it("reopens with an empty quantity and no question after a cancel", () => {
    openDialog();
    fireEvent.change(screen.getByTestId("maker-complete-actual-qty-input"), {
      target: { value: "59" },
    });
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Cancel",
      }),
    );
    fireEvent.click(screen.getByText("open"));

    expect(
      (
        screen.getByTestId(
          "maker-complete-actual-qty-input",
        ) as HTMLInputElement
      ).value,
    ).toBe("");
    expect(screen.queryByTestId("maker-overproduction-notice")).toBeNull();
  });
});
