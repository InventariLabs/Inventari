import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { POActionBar } from "./POActionBar";
import type { PurchaseOrder } from "../types/purchase-orders";

const phone = vi.hoisted(() => ({ value: true }));
vi.mock("@/hooks/useMediaQuery", () => ({
  useMediaQuery: () => phone.value,
}));

const order = (over: Partial<PurchaseOrder> = {}) =>
  ({
    id: "po-1",
    number: "PO/2026/001",
    status: "CONFIRMED",
    partner_id: "partner-1",
    lines: [],
    ...over,
  }) as unknown as PurchaseOrder;

function renderBar(
  po: PurchaseOrder,
  over: Partial<Parameters<typeof POActionBar>[0]> = {},
) {
  const props = {
    po,
    canManage: true,
    canDecide: true,
    canWrite: true,
    approvalsEnabled: true,
    workflowConfigured: true,
    hasPendingApproval: false,
    pdfPending: false,
    onEdit: vi.fn(),
    onAction: vi.fn(),
    onDownloadPdf: vi.fn(),
    onReceive: vi.fn(),
    ...over,
  };
  render(<POActionBar {...props} />);
  return props;
}

/**
 * On a phone the order's actions fold into one "More actions" menu: a press
 * there must still reach the action and close the menu, and an action that
 * cannot run says why under its label — on a phone there is no hover to
 * show a title. A withdrawn request on a parked order offers asking again.
 */
describe("POActionBar — the phone menu and a withdrawn request", () => {
  beforeEach(() => {
    phone.value = true;
  });

  it("runs the pressed action from the phone menu and closes it", async () => {
    const props = renderBar(order());
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Send to supplier" }),
    );
    expect(props.onAction).toHaveBeenCalledWith("send");
    expect(
      screen.queryByRole("button", { name: "Send to supplier" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the main next step on the header row, outside the menu", async () => {
    const props = renderBar(order());
    // No menu opened: the receive button is already on the page.
    await userEvent.click(
      screen.getByRole("button", { name: "Receive delivery" }),
    );
    expect(props.onReceive).toHaveBeenCalledTimes(1);
  });

  it("says under a disabled action why it cannot run", async () => {
    renderBar(order({ partner_id: null }));
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(
      screen.getByRole("button", { name: "Receive delivery" }),
    ).toBeDisabled();
    expect(screen.getAllByText(/supplier/i).length).toBeGreaterThan(0);
  });

  it("offers asking again on a parked order with nothing pending", async () => {
    phone.value = false;
    const props = renderBar(order({ status: "PENDING_APPROVAL" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Request approval" }),
    );
    expect(props.onAction).toHaveBeenCalledWith("requestApproval");
  });

  it("offers nothing on a parked order the approval card already handles", () => {
    phone.value = false;
    renderBar(order({ status: "PENDING_APPROVAL" }), {
      approvalCardShown: true,
      canManage: false,
    });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
