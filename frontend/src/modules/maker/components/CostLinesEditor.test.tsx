import { describe, it, expect, vi } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AxiosError, type AxiosResponse } from "axios";
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

function renderEditor(
  props: Partial<React.ComponentProps<typeof CostLinesEditor>> = {},
) {
  render(
    <MemoryRouter>
      <CostLinesEditor recipeId="r-1" lines={lines} {...props} />
    </MemoryRouter>,
  );
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

  it("shows the server's refusal of a negative amount beside the Amount field", async () => {
    addMutate.mockRejectedValueOnce(
      new AxiosError(
        "Request failed",
        "ERR_BAD_REQUEST",
        undefined,
        undefined,
        {
          status: 422,
          data: {
            detail: [
              {
                loc: ["body", "amount"],
                msg: "Must be greater than or equal to 0",
                type: "greater_than_equal",
              },
            ],
          },
        } as AxiosResponse,
      ),
    );
    renderEditor();
    fireEvent.click(screen.getByTestId("maker-cost-line-add"));
    fireEvent.change(screen.getByTestId("maker-cost-line-label"), {
      target: { value: "Oven electricity" },
    });
    fireEvent.change(screen.getByTestId("maker-cost-line-amount"), {
      target: { value: "-5" },
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText("Save"));
    });

    const amount = screen.getByTestId("maker-cost-line-amount");
    expect(
      screen.getByText("Must be greater than or equal to 0"),
    ).toBeVisible();
    expect(amount).toHaveAttribute("aria-invalid", "true");
    // What was typed stays, so it can be corrected rather than retyped.
    expect(amount).toHaveValue(-5);
    expect(screen.getByTestId("maker-cost-line-label")).toHaveValue(
      "Oven electricity",
    );

    fireEvent.change(amount, { target: { value: "5" } });
    expect(
      screen.queryByText("Must be greater than or equal to 0"),
    ).not.toBeInTheDocument();
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
    // The heading already carries the unit; the sum does not say it again.
    const total = screen.getByText("PLN 16.50");
    expect(total).toBeInTheDocument();
    expect(total).not.toHaveTextContent(/batch/i);
  });

  it("does not print the amount twice when a single line is the whole sum", () => {
    renderEditor({ lines: lines.slice(0, 1) });

    expect(screen.getAllByText("PLN 12.50")).toHaveLength(1);
  });

  it("offers no total while no line exists — the caption says that instead", () => {
    // A 0.00 over "No fixed costs set" would read as a fact about costs;
    // the caption alone is the answer an empty section gives.
    renderEditor({ lines: [] });

    expect(screen.getByText("No fixed costs set")).toBeInTheDocument();
    expect(screen.queryByText(/PLN 0[.,]00/)).toBeNull();
  });
});

describe("CostLinesEditor — the computed labour line", () => {
  it("shows the batch's labour from the timed steps beside the fixed lines", () => {
    renderEditor({ labourCost: "22.50", labourMinutes: 45 });
    const row = screen.getByTestId("maker-computed-labour");
    expect(row.textContent).toContain("Labour from the process steps");
    expect(row.textContent).toContain("45 min");
    expect(row.textContent).toContain("PLN");
    expect(row.textContent).toContain("22.50");
  });

  it("leaves the row out when no step was timed, instead of claiming free labour", () => {
    renderEditor({ labourCost: "0" });
    expect(
      screen.queryByTestId("maker-computed-labour"),
    ).not.toBeInTheDocument();
  });

  it("points at the hourly rate when the steps are timed but nothing prices them", () => {
    // At a zero rate the line is absent, which read as "this formula has no
    // labour" — the rate was two screens away under Advanced.
    renderEditor({ labourCost: "0", labourMinutes: 45 });
    const hint = screen.getByTestId("maker-labour-rate-hint");
    expect(hint).toHaveTextContent(/45 min/);
    expect(hint).toHaveTextContent(/hourly rate/i);
    expect(
      screen.getByRole("link", { name: /production settings/i }),
    ).toHaveAttribute("href", "/maker/settings");
  });
});
