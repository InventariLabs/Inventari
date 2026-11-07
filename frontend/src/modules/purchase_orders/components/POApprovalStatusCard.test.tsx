import { describe, expect, it, vi } from "vitest";

const requirement = vi.hoisted(() => ({
  answer: undefined as
    | undefined
    | {
        approval_required: boolean;
        approval_solvable: boolean;
        undecidable_reason: string | null;
        undecidable_stage: string | null;
      },
}));
const slot = vi.hoisted(() => ({
  data: undefined as undefined | { requestConsequence?: string },
}));

vi.mock("../hooks/usePurchaseOrders", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../hooks/usePurchaseOrders")>();
  return { ...actual, usePOApprovalRequirement: () => requirement.answer };
});

vi.mock("@/hooks/useHasPermission", () => ({
  useHasPermission: () => true,
}));

// The slot is the approvals module's; here it only shows what the card handed it.
vi.mock("@/components/Slot", () => ({
  TypedSlot: (props: { data: { requestConsequence?: string } }) => {
    slot.data = props.data;
    return <p>{props.data.requestConsequence}</p>;
  },
}));

import { render, screen } from "@/test/utils";
import { POApprovalStatusCard } from "./POApprovalStatusCard";
import type { PurchaseOrder } from "../types/purchase-orders";

const po = { id: "po-1", number: "PO/2026/017" } as PurchaseOrder;

function renderCard() {
  return render(
    <POApprovalStatusCard
      po={po}
      onApprove={vi.fn()}
      onRequest={vi.fn()}
      onReject={vi.fn()}
    />,
  );
}

describe("POApprovalStatusCard", () => {
  it("asks with the dead end named when a withdrawn order's next request would park", () => {
    requirement.answer = {
      approval_required: true,
      approval_solvable: false,
      undecidable_reason: "named_approvers_cannot_decide",
      undecidable_stage: "Director",
    };
    renderCard();
    expect(slot.data?.requestConsequence).toContain("Director");
    expect(screen.getByText(/Director/)).toBeInTheDocument();
  });

  it("asks with the plain sentence when somebody can decide", () => {
    requirement.answer = undefined;
    renderCard();
    expect(slot.data?.requestConsequence).toContain("PO/2026/017");
  });

  it("links to the approval queue by an address that names its open tab", () => {
    requirement.answer = undefined;
    renderCard();
    // `?status=pending` names no tab: the queue opened on Open while the
    // address read as if it were a tab of its own. The bare address is the
    // one the Open tab itself shows.
    expect(
      screen.getByRole("link", { name: "Open approval queue" }),
    ).toHaveAttribute("href", "/approvals");
  });
});
