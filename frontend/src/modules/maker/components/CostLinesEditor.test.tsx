import { describe, it, expect, vi } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { CostLinesEditor } from "./CostLinesEditor";
import type { RecipeCostLine } from "@/modules/maker/types/maker";

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

const addMutate = vi.fn();
const updateMutate = vi.fn();
const deleteMutate = vi.fn();

vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useAddCostLine: () => ({ mutateAsync: addMutate, isPending: false }),
  useUpdateCostLine: () => ({ mutateAsync: updateMutate, isPending: false }),
  useDeleteCostLine: () => ({ mutate: deleteMutate, isPending: false }),
}));

const lines: RecipeCostLine[] = [
  {
    id: "cl-1",
    recipe_id: "r-1",
    kind: "LABOR",
    label: "Oven time",
    amount: "12.50",
    sort_order: 0,
  },
  {
    id: "cl-2",
    recipe_id: "r-1",
    kind: "PACKAGING",
    label: "Jars",
    amount: "4.00",
    sort_order: 1,
  },
];

function renderEditor() {
  render(<CostLinesEditor recipeId="r-1" lines={lines} />);
}

describe("CostLinesEditor", () => {
  it("lists existing cost lines with kind badge and formatted amount", () => {
    renderEditor();
    expect(screen.getByText("Oven time")).toBeInTheDocument();
    expect(screen.getByText("Labor")).toBeInTheDocument();
    expect(screen.getByText("PLN 12.50")).toBeInTheDocument();
    expect(screen.getByText("Jars")).toBeInTheDocument();
    expect(screen.getByText("Packaging")).toBeInTheDocument();
  });

  it("lets a cost line wrap, and keeps the label a readable width", () => {
    // jsdom has no layout, so the wrap is pinned by its classes. At 320px the
    // label shared one row with the badge, the amount and two icons and was
    // left 18px: "S…" for "Stirring and jarring".
    renderEditor();
    const label = screen.getByText("Oven time");
    expect(label.className).toContain("min-w-[7rem]");
    expect(label.parentElement?.className).toContain("flex-wrap");
    // The amount and the actions travel as one group, so they drop under the
    // label together instead of one by one.
    const amount = screen.getByText("PLN 12.50");
    expect(amount.parentElement?.className).toContain("ml-auto");
    expect(amount.parentElement?.parentElement).toBe(label.parentElement);
  });

  it("adds a new cost line via the create form", async () => {
    renderEditor();
    fireEvent.click(screen.getByTestId("maker-cost-line-add"));

    fireEvent.change(screen.getByTestId("maker-cost-line-kind"), {
      target: { value: "OVERHEAD" },
    });
    fireEvent.change(screen.getByTestId("maker-cost-line-label"), {
      target: { value: "Electricity" },
    });
    fireEvent.change(screen.getByTestId("maker-cost-line-amount"), {
      target: { value: "8.75" },
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText("Save"));
    });

    expect(addMutate).toHaveBeenCalledWith({
      recipeId: "r-1",
      data: { kind: "OVERHEAD", label: "Electricity", amount: "8.75" },
    });
  });

  it("does not save an invalid draft", () => {
    renderEditor();
    fireEvent.click(screen.getByTestId("maker-cost-line-add"));
    fireEvent.change(screen.getByTestId("maker-cost-line-label"), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByTestId("maker-cost-line-amount"), {
      target: { value: "abc" },
    });
    fireEvent.click(screen.getByLabelText("Save"));
    expect(addMutate).not.toHaveBeenCalled();
  });

  it("updates an existing cost line", async () => {
    renderEditor();
    const editButtons = screen.getAllByLabelText("Edit");
    fireEvent.click(editButtons[0]);

    fireEvent.change(screen.getByTestId("maker-cost-line-amount"), {
      target: { value: "15.00" },
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText("Save"));
    });

    expect(updateMutate).toHaveBeenCalledWith({
      recipeId: "r-1",
      lineId: "cl-1",
      data: { kind: "LABOR", label: "Oven time", amount: "15.00" },
    });
  });

  it("deletes a cost line after confirmation", () => {
    renderEditor();
    const deleteButtons = screen.getAllByLabelText("Delete");
    fireEvent.click(deleteButtons[0]);

    const confirmButtons = screen.getAllByRole("button", { name: "Delete" });
    fireEvent.click(confirmButtons[confirmButtons.length - 1]);

    expect(deleteMutate).toHaveBeenCalledWith(
      { recipeId: "r-1", lineId: "cl-1" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });
  it("says which currency the amount is in", () => {
    // The only money field in the app without a currency marker — while the
    // saved line right above it renders with the organization's.
    renderEditor();
    fireEvent.click(screen.getByTestId("maker-cost-line-add"));

    const amount = screen.getByTestId("maker-cost-line-amount");
    expect(amount.parentElement?.textContent).toContain("PLN");
  });

  it("carries the fixed-cost total in the section header, named once", () => {
    // The cost tab printed this section's heading twice — once on a summary
    // card, once here. The total now sits beside the lines it sums, and the
    // heading appears once.
    renderEditor();

    expect(screen.getAllByText("Fixed costs / batch")).toHaveLength(1);
    const total = screen.getByText("PLN 16.50");
    expect(total).toBeInTheDocument();
    // The space is text, not just the margin: "16.50per batch" is one word
    // to a screen reader.
    expect(total).toHaveTextContent(/PLN 16\.50 per batch/);
  });

  it("offers no total while no line exists — the caption says that instead", () => {
    // A 0.00 over "No fixed costs set" would read as a fact about costs;
    // the caption alone is the answer an empty section gives.
    render(<CostLinesEditor recipeId="r-1" lines={[]} />);

    expect(screen.getByText("No fixed costs set")).toBeInTheDocument();
    expect(screen.queryByText(/PLN 0[.,]00/)).toBeNull();
  });
});
