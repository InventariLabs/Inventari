import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/test/utils";
import { IngredientBatchPicker } from "@/modules/maker/components/IngredientBatchPicker";
import type { BatchChoice } from "@/modules/maker/hooks/useBatchChoice";
import type { IngredientBatchPlan } from "@/modules/maker/types/maker";

const honey: IngredientBatchPlan = {
  template_id: "honey",
  template_name: "Honey",
  uom_symbol: "kg",
  needed: "6",
  plan: [{ lot_id: "early", lot_name: "H-EARLY", quantity: "6" }],
  batches: [
    { lot_id: "early", lot_name: "H-EARLY", available: "10" },
    { lot_id: "late", lot_name: "H-LATE", available: "4" },
  ],
};

function choice(over: Partial<BatchChoice> = {}): BatchChoice {
  return {
    plans: [honey],
    choices: {},
    choose: vi.fn(),
    short: new Set<string>(),
    payload: [],
    isError: false,
    error: null,
    refetch: vi.fn(),
    ...over,
  } as unknown as BatchChoice;
}

describe("IngredientBatchPicker", () => {
  it("shows the batch the run takes by default and every batch on offer", () => {
    render(<IngredientBatchPicker choice={choice()} />);

    const select = screen.getByTestId("maker-batch-select-honey");
    expect(select).toHaveDisplayValue(/H-EARLY/);
    expect(screen.getByRole("option", { name: /H-LATE/ })).toBeInTheDocument();
  });

  it("chooses the batch whose label is scanned", () => {
    const state = choice();
    render(<IngredientBatchPicker choice={state} />);

    const scan = screen.getByTestId("maker-batch-scan-input");
    fireEvent.change(scan, { target: { value: "H-LATE" } });
    fireEvent.keyDown(scan, { key: "Enter" });

    expect(state.choose).toHaveBeenCalledWith("honey", "late");
  });

  it("says when a scanned code is no batch of these ingredients", () => {
    render(<IngredientBatchPicker choice={choice()} />);

    const scan = screen.getByTestId("maker-batch-scan-input");
    fireEvent.change(scan, { target: { value: "X-9" } });
    fireEvent.keyDown(scan, { key: "Enter" });

    expect(
      screen.getByText(/no ingredient of this run has a batch X-9/i),
    ).toBeInTheDocument();
  });

  it("warns when the chosen batch has less than the run needs", () => {
    render(
      <IngredientBatchPicker
        choice={choice({
          choices: { honey: "late" },
          short: new Set(["honey"]),
        })}
      />,
    );

    expect(
      screen.getByText("This batch has less free than the run needs."),
    ).toBeInTheDocument();
  });

  it("shows nothing for a run none of whose ingredients is kept in batches", () => {
    render(
      <IngredientBatchPicker
        choice={choice({ plans: [{ ...honey, batches: [], plan: [] }] })}
      />,
    );

    expect(screen.queryByTestId("maker-ingredient-batches")).toBeNull();
  });
});
