import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import type { TargetApprovalRequest } from "@/lib/moduleRegistry";
import { ApprovalParkedRequestsSlot } from "./ApprovalParkedRequestsSlot";

const readRequests = vi.hoisted(() => vi.fn());
vi.mock("@/modules/approvals/hooks/useApprovalRequests", () => ({
  useApprovalRequests: readRequests,
}));

function request(overrides: Partial<TargetApprovalRequest>) {
  return {
    id: "req-1",
    organization_id: "org-1",
    workflow_id: "wf-1",
    target_type: "document",
    target_id: "doc-1",
    status: "PENDING",
    current_stage: 1,
    total_stages: 1,
    created_by: "user-1",
    created_by_name: "Alice",
    meta_data: null,
    workflow_stages: [
      { order: 1, role: "manager", label: "Manager", approver_user_ids: [] },
    ],
    decisions: [],
    created_at: new Date().toISOString(),
    target_summary: { number: "IN/2026/0001" },
    solvable: false,
    undecidable_reason: "named_approvers_cannot_decide",
    ...overrides,
  } as unknown as TargetApprovalRequest;
}

function renderSlot() {
  return render(
    <ApprovalParkedRequestsSlot
      data={{
        targetType: "document",
        targetHref: (id) => `/warehouse/documents/${id}`,
      }}
    />,
  );
}

describe("ApprovalParkedRequestsSlot", () => {
  beforeEach(() => {
    readRequests.mockReset();
  });

  it("asks for the open requests of the target type", () => {
    readRequests.mockReturnValue({ data: { items: [] } });
    renderSlot();

    expect(readRequests).toHaveBeenCalledWith({
      target_type: "document",
      status: "PENDING,IN_PROGRESS",
      limit: 100,
    });
  });

  it("names a request parked at a stage nobody can decide, linking to its record", () => {
    // Such a request never reaches a decider's queue, so without this section
    // it reads exactly like an empty one.
    readRequests.mockReturnValue({ data: { items: [request({})] } });
    renderSlot();

    expect(screen.getByText("Parked — nobody can decide")).toBeInTheDocument();
    expect(
      screen.getByText("Nobody can decide this request"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /IN\/2026\/0001/ }),
    ).toHaveAttribute("href", "/warehouse/documents/doc-1");
    expect(screen.getByText(/Alice · requested this/)).toBeInTheDocument();
  });

  it("says nothing about a request somebody can decide", () => {
    readRequests.mockReturnValue({
      data: { items: [request({ solvable: true, undecidable_reason: null })] },
    });
    const { container } = renderSlot();

    expect(container).toBeEmptyDOMElement();
  });

  it("says the read failed instead of naming none parked", () => {
    readRequests.mockReturnValue({
      data: undefined,
      isError: true,
      error: new Error("boom"),
      refetch: vi.fn(),
    });
    renderSlot();

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });
});
