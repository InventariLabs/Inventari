import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { DocumentCostVariancesSection } from "./DocumentCostVariancesSection";

const addMutate = vi.hoisted(() => vi.fn());
const removeMutate = vi.hoisted(() => vi.fn());
const rights = vi.hoisted(() => ({ manage: true }));

let view: Record<string, unknown> | undefined;

vi.mock("@/hooks/useCanWrite", () => ({
  useCanManage: () => rights.manage,
}));

vi.mock("@/modules/warehouse/hooks/useExtraCosts", () => ({
  useExtraCosts: () => ({ data: view }),
  useAddCostVariance: () => ({ mutate: addMutate, isPending: false }),
  useRemoveCostVariance: () => ({ mutate: removeMutate, isPending: false }),
}));

// The real DateInput is a popover with its own calendar; these tests only
// need to know which day was picked.
vi.mock("@/components/ui/DateInput", () => ({
  DateInput: (props: {
    label: string;
    value: string;
    onChange: (value: string) => void;
  }) => (
    <input
      aria-label={props.label}
      value={props.value}
      onChange={(event) => props.onChange(event.target.value)}
    />
  ),
}));

const posted = {
  costs: [],
  total: "0",
  currency: "USD",
  editable: false,
  fell_back: [],
  lines: [],
  variances: [
    {
      id: "v1",
      document_id: "doc-1",
      kind: "freight",
      amount: "200.00",
      currency: "USD",
      reason: "Invoiced after posting",
      occurred_on: "2026-11-10",
    },
  ],
  variance_total: "200.00",
};

describe("DocumentCostVariancesSection", () => {
  afterEach(() => vi.useRealTimers());

  beforeEach(() => {
    addMutate.mockClear();
    removeMutate.mockClear();
    rights.manage = true;
    view = { ...posted };
    vi.useFakeTimers({ toFake: ["Date"], now: new Date(2026, 10, 12, 12) });
  });

  it("lists what was recorded, with its reason, and adds it up", () => {
    renderWithProviders(<DocumentCostVariancesSection documentId="doc-1" />);

    expect(screen.getByText(/Invoiced after posting/)).toBeInTheDocument();
    // The row and the total both carry the amount.
    expect(screen.getAllByText(/200[.,]00/)).toHaveLength(2);
    expect(
      screen.getByText(/never becomes part of the stock value/i),
    ).toBeTruthy();
  });

  it("sends the variance with the reason the form was given", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DocumentCostVariancesSection documentId="doc-1" />);

    await user.type(screen.getByLabelText("Amount"), "50");
    await user.type(screen.getByLabelText("Reason"), "Late invoice");
    await user.click(
      screen.getByRole("button", { name: /record as variance/i }),
    );

    expect(addMutate).toHaveBeenCalledWith(
      {
        kind: "freight",
        amount: "50",
        reason: "Late invoice",
        occurred_on: "2026-11-12",
      },
      expect.anything(),
    );
  });

  it("sends the day the cost belongs to, not the day it was typed", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DocumentCostVariancesSection documentId="doc-1" />);

    await user.type(screen.getByLabelText("Amount"), "50");
    await user.type(screen.getByLabelText("Reason"), "Freight bill");
    const day = screen.getByLabelText("Day it belongs to");
    await user.clear(day);
    await user.type(day, "2026-11-10");
    await user.click(
      screen.getByRole("button", { name: /record as variance/i }),
    );

    expect(addMutate).toHaveBeenCalledWith(
      expect.objectContaining({ occurred_on: "2026-11-10" }),
      expect.anything(),
    );
  });

  it("will not send an amount without a reason", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DocumentCostVariancesSection documentId="doc-1" />);

    await user.type(screen.getByLabelText("Amount"), "50");

    expect(
      screen.getByRole("button", { name: /record as variance/i }),
    ).toBeDisabled();
  });

  it("does not offer the form while the receipt is open — the cost goes into the goods", () => {
    view = { ...posted, editable: true, variances: [] };

    const { container } = renderWithProviders(
      <DocumentCostVariancesSection documentId="doc-1" />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("is a read-only list for someone who cannot manage the module", () => {
    rights.manage = false;

    renderWithProviders(<DocumentCostVariancesSection documentId="doc-1" />);

    expect(screen.getByText(/Invoiced after posting/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Reason")).toBeNull();
    expect(screen.queryByRole("button", { name: /remove/i })).toBeNull();
  });

  it("removes a variance", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DocumentCostVariancesSection documentId="doc-1" />);

    await user.click(
      screen.getByRole("button", { name: /remove this variance/i }),
    );

    expect(removeMutate).toHaveBeenCalledWith("v1");
  });
});
