import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ReplenishSheet } from "./ReplenishSheet";
import type { WorkItem } from "@/modules/warehouse/types";

const postMutate = vi.hoisted(() => vi.fn());
const proposal = vi.hoisted(() => ({
  value: {
    reorder_rule_id: "rule-1",
    product_template_id: "tpl-1",
    product_name: "Jasmine Rice",
    target_location_id: "loc-pick",
    target_location_name: "Pick B-01",
    quantity: "17",
    unit: "pcs",
    lines: [
      {
        item_id: "item-1",
        product_template_id: "tpl-1",
        product_name: "Jasmine Rice",
        lot_id: "lot-1",
        lot_name: "LOT-EARLY",
        expiry_date: "2026-11-01",
        source_location_id: "loc-reserve",
        source_location_name: "Reserve R-12",
        quantity: "17",
        uom_id: "uom-1",
        uom_symbol: "pcs",
      },
    ],
  } as Record<string, unknown>,
}));
const profile = vi.hoisted(() => ({ confirm_shelf_by_scan: false }));

vi.mock("@/modules/warehouse/hooks/useWorkItems", () => ({
  useReplenishmentProposal: () => ({
    data: proposal.value,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
  usePostReplenishmentProposal: () => ({
    mutate: postMutate,
    isPending: false,
  }),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({ data: profile }),
}));

const item: WorkItem = {
  key: "replenishment:rule-1",
  kind: "replenish",
  state: "todo",
  source_kind: "replenishment",
  source_id: "rule-1",
  subject: "Jasmine Rice",
  count: "17",
  unit: "pcs",
  place: "Pick B-01",
  next_action: "replenish",
  shelf_scan_required: false,
  overdue: false,
};

describe("ReplenishSheet", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    profile.confirm_shelf_by_scan = false;
  });

  it("shows the prepared lines and posts the move", async () => {
    render(<ReplenishSheet item={item} onClose={vi.fn()} />);

    expect(
      screen.getByText("Reserve R-12", { exact: false }),
    ).toBeInTheDocument();
    expect(screen.getByText("LOT-EARLY", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("To Pick B-01")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Post the move" }),
    );
    expect(postMutate).toHaveBeenCalledWith(
      { ruleId: "rule-1", scannedCode: undefined },
      expect.anything(),
    );
  });

  it("asks for the reserve shelf scan where the profile requires one", async () => {
    profile.confirm_shelf_by_scan = true;
    render(<ReplenishSheet item={item} onClose={vi.fn()} />);

    const post = screen.getByRole("button", { name: "Post the move" });
    expect(post).toBeDisabled();

    await userEvent.type(
      screen.getByRole("textbox", { name: "Scan the reserve location" }),
      "R-12",
    );
    expect(post).toBeEnabled();
    await userEvent.click(post);
    await waitFor(() =>
      expect(postMutate).toHaveBeenCalledWith(
        { ruleId: "rule-1", scannedCode: "R-12" },
        expect.anything(),
      ),
    );
  });

  it("says an expired proposal moved nothing", () => {
    proposal.value = { ...proposal.value, lines: [], quantity: "0" };
    render(<ReplenishSheet item={item} onClose={vi.fn()} />);

    expect(
      screen.getByText(/This proposal no longer stands/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Post the move" }),
    ).toBeDisabled();
  });
});
