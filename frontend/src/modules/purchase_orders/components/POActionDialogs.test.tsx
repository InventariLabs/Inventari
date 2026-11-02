import { afterEach, describe, expect, it, vi } from "vitest";

const settingsFlag = vi.hoisted(() => ({
  approvalRequired: true,
  approvalThreshold: null as string | null,
}));
const orgCurrency = vi.hoisted(() => ({ code: "EUR" as string | undefined }));
const permission = vi.hoisted(() => ({ isAdmin: true }));
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

// The dialog reads the organization's own setting; the mock stands in for
// GET /purchase-orders/settings so each side of the flag is exercisable.
vi.mock("../hooks/usePurchaseOrders", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../hooks/usePurchaseOrders")>();
  return {
    ...actual,
    usePOApprovalRequirement: () => requirement.answer,
    usePOSettings: () => ({
      data: {
        approval_required: settingsFlag.approvalRequired,
        approval_threshold: settingsFlag.approvalThreshold,
      },
    }),
  };
});

vi.mock("@/hooks/useHasPermission", () => ({
  useHasPermission: () => permission.isAdmin,
}));

// The threshold is denominated in the organization's currency, and an order
// in any other currency is routed to approval whatever its total.
vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => orgCurrency.code,
}));

import { render, screen } from "@/test/utils";
import { POActionDialogs, type POActionType } from "./POActionDialogs";
import type { PurchaseOrder } from "../types/purchase-orders";

function makePo(overrides: Partial<PurchaseOrder> = {}) {
  return {
    id: "po-1",
    number: "PO/2026/017",
    currency: "EUR",
    lines: [{ id: "l-1", unit_price: "10.00", quantity_ordered: 1 }],
    ...overrides,
  } as unknown as PurchaseOrder;
}

function renderDialogs(
  po: PurchaseOrder = makePo(),
  actionType: POActionType = "confirm",
) {
  return render(
    <POActionDialogs
      po={po}
      actionType={actionType}
      partnerEmail={null}
      onConfirm={vi.fn()}
      onCancel={vi.fn()}
      onReject={vi.fn()}
    />,
  );
}

describe("POActionDialogs", () => {
  it("with the approval gate on, confirming names the queue, not receiving", () => {
    settingsFlag.approvalRequired = true;
    settingsFlag.approvalThreshold = null;
    orgCurrency.code = "EUR";
    renderDialogs();

    // The gate parks the order in PENDING_APPROVAL, where receiving is
    // refused — the dialog may only promise the queue and the approval
    // that follows it.
    expect(screen.getByText(/approval queue/)).toBeInTheDocument();
    expect(screen.getByText(/once it is approved/)).toBeInTheDocument();
    expect(
      screen.queryByText(/once the order is confirmed/),
    ).not.toBeInTheDocument();
    // Cancelling stays possible from the approval queue, so the promise
    // about cancelling survives.
    expect(screen.getByText(/still cancel it afterwards/)).toBeInTheDocument();
  });

  it("with no gate and no threshold, it promises receiving and names no queue", () => {
    // `_is_approval_required` returns False before it ever looks at the
    // currency or the total when the threshold is unset
    // (backend `_service_workflow.py`: `if threshold is None: return False`),
    // so nothing about this confirmation is conditional and the reader is
    // handed no condition to resolve.
    settingsFlag.approvalRequired = false;
    settingsFlag.approvalThreshold = null;
    orgCurrency.code = "EUR";
    renderDialogs();

    expect(screen.getByText(/once the order is confirmed/)).toBeInTheDocument();
    expect(screen.queryByText(/approval queue/)).not.toBeInTheDocument();
    expect(screen.queryByText(/If your organization/)).not.toBeInTheDocument();
    expect(screen.getByText(/still cancel it afterwards/)).toBeInTheDocument();
  });

  it("with a threshold configured, it names the threshold instead of a condition", () => {
    // Here the queue is a real outcome, so the sentence may not promise
    // receiving outright — but what decides is a number this organization
    // configured, and the dialog states it rather than asking the reader
    // whether their organization has one.
    settingsFlag.approvalRequired = false;
    settingsFlag.approvalThreshold = "1000.00";
    orgCurrency.code = "EUR";
    renderDialogs();

    expect(screen.getByText(/1,000\.00/)).toBeInTheDocument();
    expect(screen.getByText(/approval queue/)).toBeInTheDocument();
    expect(screen.queryByText(/If your organization/)).not.toBeInTheDocument();
  });

  it("with a threshold and a foreign currency, the queue is certain and said so", () => {
    // Cross-currency orders are routed to approval without comparing
    // numbers (there is no FX conversion), so naming the threshold here
    // would describe a comparison that never happens.
    settingsFlag.approvalRequired = false;
    settingsFlag.approvalThreshold = "1000.00";
    orgCurrency.code = "EUR";
    renderDialogs(makePo({ currency: "USD" }));

    expect(screen.getByText(/once it is approved/)).toBeInTheDocument();
    expect(screen.queryByText(/1,000\.00/)).not.toBeInTheDocument();
  });

  it("with a threshold and an unpriced line, the queue is certain and said so", () => {
    // A total nobody can state is not a total below the limit — the
    // backend routes it to approval, so the dialog may not offer the
    // threshold as the thing that decides this order as it stands.
    settingsFlag.approvalRequired = false;
    settingsFlag.approvalThreshold = "1000.00";
    orgCurrency.code = "EUR";
    renderDialogs(
      makePo({
        lines: [
          { id: "l-1", unit_price: null, quantity_ordered: 1 },
        ] as unknown as PurchaseOrder["lines"],
      }),
    );

    // The limit is named only as what pricing the lines would change.
    const message = screen.getByText(/once it is approved/);
    expect(message).toHaveTextContent(/total is not known/);
    expect(message).toHaveTextContent(/add the prices first/);
  });

  describe("once the server has answered", () => {
    const unpriced = () =>
      makePo({
        lines: [{ id: "l-1", unit_price: null, quantity_ordered: 1 }],
      } as unknown as Partial<PurchaseOrder>);

    const deadEnd = (reason: string) => ({
      approval_required: true,
      approval_solvable: false,
      undecidable_reason: reason,
      undecidable_stage: "Team lead",
    });

    afterEach(() => {
      requirement.answer = undefined;
      permission.isAdmin = true;
    });

    it("calls an order only the requester could decide a dead end, not the queue", () => {
      settingsFlag.approvalRequired = true;
      settingsFlag.approvalThreshold = null;
      requirement.answer = deadEnd("only_the_requester_can_decide");
      renderDialogs();

      expect(
        screen.getByText(/Nobody can decide this request/),
      ).toBeInTheDocument();
      const message = screen.getByText(/“Team lead”/);
      expect(message).toHaveTextContent(/only holder is the person who asked/);
      // What would lift it, for the reader who can: an administrator here.
      expect(message).toHaveTextContent(/someone the approve permission/);
      expect(message).toHaveTextContent(/approve their own requests/);
      expect(screen.queryByText(/approval queue/)).not.toBeInTheDocument();
    });

    it.each([
      ["named_approvers_cannot_decide", /cannot see approvals/],
      ["no_approver_in_organization", /nobody in this organization holds it/],
    ])("says why for %s", (reason, sentence) => {
      settingsFlag.approvalRequired = true;
      requirement.answer = deadEnd(reason);
      renderDialogs();

      expect(screen.getByText(sentence)).toBeInTheDocument();
    });

    it("reads as sentences: the title ends before the cause begins", () => {
      settingsFlag.approvalRequired = true;
      settingsFlag.approvalThreshold = null;
      requirement.answer = deadEnd("only_the_requester_can_decide");
      renderDialogs();

      expect(screen.getByText(/“Team lead”/)).toHaveTextContent(
        /Nobody can decide this request\. The stage is open/,
      );
    });

    it("tells a reader who cannot give the access whom to ask", () => {
      settingsFlag.approvalRequired = true;
      settingsFlag.approvalThreshold = null;
      permission.isAdmin = false;
      requirement.answer = deadEnd("only_the_requester_can_decide");
      renderDialogs();

      const message = screen.getByText(/“Team lead”/);
      expect(message).toHaveTextContent(/Ask an administrator/);
      expect(message).not.toHaveTextContent(/approve their own requests/);
    });

    it("names pricing as the way out when the missing price is what holds the order", () => {
      settingsFlag.approvalRequired = false;
      settingsFlag.approvalThreshold = "10000.00";
      orgCurrency.code = "EUR";
      requirement.answer = deadEnd("only_the_requester_can_decide");
      renderDialogs(unpriced());

      const message = screen.getByText(/Nobody can decide this request/);
      expect(message).toHaveTextContent(/no price yet/);
      expect(message).toHaveTextContent(/add the prices first/);
    });

    it("does not offer pricing where a price would not lift the approval", () => {
      settingsFlag.approvalRequired = true;
      settingsFlag.approvalThreshold = "10000.00";
      requirement.answer = deadEnd("only_the_requester_can_decide");
      renderDialogs(unpriced());

      expect(
        screen.getByText(/Nobody can decide this request/),
      ).not.toHaveTextContent(/add the prices first/);
    });

    it("promises the queue where somebody can decide", () => {
      settingsFlag.approvalRequired = false;
      settingsFlag.approvalThreshold = "10000.00";
      requirement.answer = {
        approval_required: true,
        approval_solvable: true,
        undecidable_reason: null,
        undecidable_stage: null,
      };
      renderDialogs(unpriced());

      const message = screen.getByText(/approval queue/);
      expect(message).toHaveTextContent(/total is not known/);
    });

    it("promises no queue to a person the workflow does not hold", () => {
      settingsFlag.approvalRequired = true;
      settingsFlag.approvalThreshold = null;
      requirement.answer = {
        approval_required: false,
        approval_solvable: true,
        undecidable_reason: null,
        undecidable_stage: null,
      };
      renderDialogs();

      expect(screen.queryByText(/approval queue/)).not.toBeInTheDocument();
    });

    it("confirming an order no rule holds names no dead end it will not reach", () => {
      settingsFlag.approvalRequired = false;
      settingsFlag.approvalThreshold = null;
      requirement.answer = {
        ...deadEnd("only_the_requester_can_decide"),
        approval_required: false,
      };
      renderDialogs();

      expect(
        screen.getByText(/once the order is confirmed/),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(/Nobody can decide this request/),
      ).not.toBeInTheDocument();
    });

    describe("asking for approval by hand", () => {
      it("names the dead end even where no rule requires the approval", () => {
        // Request approval parks the order whatever the rules say, so the
        // server's verdict stands where `approval_required` is false.
        settingsFlag.approvalRequired = false;
        settingsFlag.approvalThreshold = null;
        requirement.answer = {
          ...deadEnd("only_the_requester_can_decide"),
          approval_required: false,
        };
        renderDialogs(makePo(), "requestApproval");

        const message = screen.getByText(/“Team lead”/);
        expect(message).toHaveTextContent(
          /Nobody can decide this request\. The stage is open/,
        );
        expect(message).toHaveTextContent(
          /only holder is the person who asked/,
        );
        expect(message).toHaveTextContent(/someone the approve permission/);
        expect(message).toHaveTextContent(/PO\/2026\/017/);
        expect(message).not.toHaveTextContent(/until an approver decides/);
      });

      it.each([
        ["named_approvers_cannot_decide", /cannot see approvals/],
        ["no_approver_in_organization", /nobody in this organization holds it/],
      ])("says why for %s", (reason, sentence) => {
        requirement.answer = deadEnd(reason);
        renderDialogs(makePo(), "requestApproval");

        expect(screen.getByText(/“Team lead”/)).toHaveTextContent(sentence);
      });

      it("tells a reader who cannot give the access whom to ask", () => {
        permission.isAdmin = false;
        requirement.answer = deadEnd("only_the_requester_can_decide");
        renderDialogs(makePo(), "requestApproval");

        const message = screen.getByText(/“Team lead”/);
        expect(message).toHaveTextContent(/Ask an administrator/);
        expect(message).not.toHaveTextContent(/approve their own requests/);
      });

      it("promises an approver where somebody can decide", () => {
        requirement.answer = {
          approval_required: false,
          approval_solvable: true,
          undecidable_reason: null,
          undecidable_stage: null,
        };
        renderDialogs(makePo(), "requestApproval");

        expect(screen.getByText(/until an approver decides/)).toHaveTextContent(
          /PO\/2026\/017/,
        );
        expect(
          screen.queryByText(/Nobody can decide this request/),
        ).not.toBeInTheDocument();
      });

      it("stands on the old sentence before the server has answered", () => {
        renderDialogs(makePo(), "requestApproval");

        expect(
          screen.getByText(/until an approver decides/),
        ).toBeInTheDocument();
      });
    });
  });
});
