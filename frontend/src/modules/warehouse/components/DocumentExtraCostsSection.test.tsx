import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { DocumentExtraCostsSection } from "./DocumentExtraCostsSection";

const addMutate = vi.hoisted(() => vi.fn());
const removeMutate = vi.hoisted(() => vi.fn());

let view: Record<string, unknown> | undefined = {
  costs: [
    {
      id: "c1",
      document_id: "doc-1",
      kind: "freight",
      amount: "200.00",
      currency: null,
      allocation_method: "value",
      note: null,
    },
  ],
  total: "200.00",
  currency: "USD",
  editable: true,
  fell_back: [],
  lines: [
    {
      line_id: "l1",
      product_name: "Rye flour",
      quantity: "100.000",
      unit_price: "10.00",
      surcharge: "200.00",
      unit_cost_after: "12.00",
    },
  ],
};

vi.mock("@/modules/warehouse/hooks/useExtraCosts", () => ({
  useExtraCosts: () => ({ data: view }),
  useAddExtraCost: () => ({ mutate: addMutate, isPending: false }),
  useRemoveExtraCost: () => ({ mutate: removeMutate, isPending: false }),
}));

describe("DocumentExtraCostsSection", () => {
  beforeEach(() => {
    addMutate.mockClear();
    removeMutate.mockClear();
  });

  it("says what the unit cost becomes before anybody posts", () => {
    renderWithProviders(<DocumentExtraCostsSection documentId="doc-1" />);

    // The whole point of the section: 12.00 instead of 10.00, on screen,
    // while it can still be changed.
    // `useMoney` formats with the organization's currency, which the test
    // harness has no opinion about — so this asks for the numbers.
    expect(screen.getByText(/10[.,]00/)).toBeInTheDocument();
    expect(screen.getByText(/12[.,]00/)).toBeInTheDocument();
  });

  it("sends the cost the way the form was filled in", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DocumentExtraCostsSection documentId="doc-1" />);

    await user.type(screen.getByLabelText("Amount"), "50");
    await user.click(screen.getByRole("button", { name: /add/i }));

    expect(addMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "freight",
        amount: "50",
        allocation_method: "value",
      }),
      expect.anything(),
    );
  });

  it("stops offering the form once the receipt is posted", () => {
    view = { ...(view as object), editable: false };

    renderWithProviders(<DocumentExtraCostsSection documentId="doc-1" />);

    // What the goods cost stays readable; changing it does not, because the
    // goods may already have left.
    expect(screen.getAllByText(/200[.,]00/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /add/i })).toBeNull();
    expect(screen.queryByLabelText("Amount")).toBeNull();
  });

  it("adds nothing to a posted receipt that never carried a cost", () => {
    view = { ...(view as object), editable: false, costs: [], lines: [] };

    const { container } = renderWithProviders(
      <DocumentExtraCostsSection documentId="doc-1" />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
