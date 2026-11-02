import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApprovalStageStepper } from "../components/ApprovalStageStepper";
import type { StageDefinition, ApprovalDecision } from "../api/approvals";

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

const sampleStages: StageDefinition[] = [
  {
    order: 1,
    label: "Manager Approval",
    approver_user_ids: [],
  },
  {
    order: 2,
    label: "Director Approval",
    approver_user_ids: [],
  },
  { order: 3, label: "Admin Approval", approver_user_ids: [] },
];

const sampleDecision = (
  stage_order: number,
  status: "APPROVED" | "REJECTED",
  approver_name: string,
  notes: string | null = null,
  decided_at: string | null = "2026-07-20T10:00:00Z",
): ApprovalDecision => ({
  id: `dec-${stage_order}`,
  stage_order,
  approver_id: "u-1",
  approver_name,
  status,
  notes,
  decided_at,
  created_at: decided_at ?? "2026-07-20T09:00:00Z",
});

describe("ApprovalStageStepper", () => {
  it("renders all stages with their labels", () => {
    render(
      <ApprovalStageStepper
        stages={sampleStages}
        currentStage={2}
        totalStages={3}
        status="IN_PROGRESS"
        decisions={[]}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Manager Approval")).toBeInTheDocument();
    expect(screen.getByText("Director Approval")).toBeInTheDocument();
    expect(screen.getByText("Admin Approval")).toBeInTheDocument();
  });

  it("marks the first stage as completed and shows its approver + date", () => {
    render(
      <ApprovalStageStepper
        stages={sampleStages}
        currentStage={2}
        totalStages={3}
        status="IN_PROGRESS"
        decisions={[sampleDecision(1, "APPROVED", "Alice Manager")]}
      />,
      { wrapper: createWrapper() },
    );
    // Completed stage shows approver name
    expect(screen.getByText(/Alice Manager/)).toBeInTheDocument();
    // Localised date is rendered via toLocaleDateString — at least the year
    // must appear because the seed is 2026-07-20.
    expect(screen.getByText(/2026/)).toBeInTheDocument();
  });

  it("marks the current stage with a current indicator and approver hint", () => {
    render(
      <ApprovalStageStepper
        stages={sampleStages}
        currentStage={2}
        totalStages={3}
        status="IN_PROGRESS"
        decisions={[]}
      />,
      { wrapper: createWrapper() },
    );
    // The current stage (Director) shows the "any approver may approve" hint
    // because no approver_user_ids are set.
    expect(
      screen.getByText("Any approver may approve this stage"),
    ).toBeInTheDocument();
  });

  it("renders an upcoming stage without action language", () => {
    render(
      <ApprovalStageStepper
        stages={sampleStages}
        currentStage={1}
        totalStages={3}
        status="PENDING"
        decisions={[]}
      />,
      { wrapper: createWrapper() },
    );
    // Stage 3 is upcoming — its label appears, but no "any approver" hint
    // must be shown for future stages.
    expect(screen.getByText("Admin Approval")).toBeInTheDocument();
    // Only the current stage gets the "any approver" hint. Make sure we
    // don't accidentally show it twice.
    expect(
      screen.getAllByText("Any approver may approve this stage").length,
    ).toBe(1);
  });

  it("renders a rejected stage with the rejection note", () => {
    render(
      <ApprovalStageStepper
        stages={sampleStages}
        currentStage={2}
        totalStages={3}
        status="REJECTED"
        decisions={[
          sampleDecision(2, "REJECTED", "Bob Director", "Numbers don't match"),
        ]}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText(/Bob Director/)).toBeInTheDocument();
    expect(screen.getByText(/Numbers don't match/)).toBeInTheDocument();
  });

  it("renders all stages as completed when status is APPROVED", () => {
    render(
      <ApprovalStageStepper
        stages={sampleStages}
        currentStage={3}
        totalStages={3}
        status="APPROVED"
        decisions={[
          sampleDecision(1, "APPROVED", "Alice"),
          sampleDecision(2, "APPROVED", "Bob"),
          sampleDecision(3, "APPROVED", "Carol"),
        ]}
      />,
      { wrapper: createWrapper() },
    );
    // The any-approver hint must NOT be present in a terminal APPROVED state.
    expect(
      screen.queryByText("Any approver may approve this stage"),
    ).not.toBeInTheDocument();
  });

  it("falls back to a single stage rendering when stages is null", () => {
    render(
      <ApprovalStageStepper
        stages={null}
        currentStage={1}
        totalStages={1}
        status="PENDING"
        decisions={[]}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Single approval")).toBeInTheDocument();
  });

  it("describes position instead of the process when stages are missing for a multi-stage workflow", () => {
    // missing stage data must not be presented as "Single approval"
    // when the workflow has more than one stage.
    render(
      <ApprovalStageStepper
        stages={null}
        currentStage={2}
        totalStages={2}
        status="IN_PROGRESS"
        decisions={[]}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Stage 2 of 2")).toBeInTheDocument();
    expect(screen.queryByText("Single approval")).not.toBeInTheDocument();
  });

  it("falls back to a single stage rendering when there is only one stage", () => {
    const singleStage: StageDefinition[] = [
      {
        order: 1,
        label: "Manager Approval",
        approver_user_ids: [],
      },
    ];
    render(
      <ApprovalStageStepper
        stages={singleStage}
        currentStage={1}
        totalStages={1}
        status="PENDING"
        decisions={[]}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Manager Approval")).toBeInTheDocument();
    // The single-stage fallback does not show the "any approver" hint
    // because the consumer is expected to render the action buttons
    // separately; the stepper just shows the stage label.
    expect(
      screen.queryByText("Any approver may approve this stage"),
    ).not.toBeInTheDocument();
  });

  it("shows the rejection reason on a single-stage workflow", () => {
    // Rejecting requires a reason, and single-stage workflows are
    // the common case — collapsing to the bare label meant the reason the
    // approver was forced to type never reached the requester.
    const singleStage: StageDefinition[] = [
      {
        order: 1,
        label: "Manager Approval",
        approver_user_ids: [],
      },
    ];
    render(
      <ApprovalStageStepper
        stages={singleStage}
        currentStage={1}
        totalStages={1}
        status="REJECTED"
        decisions={[
          sampleDecision(1, "REJECTED", "Bob", "Budget exceeded this quarter"),
        ]}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText("Manager Approval")).toBeInTheDocument();
    expect(
      screen.getByText('"Budget exceeded this quarter"'),
    ).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
  });

  it("shows the approval note on a single-stage workflow", () => {
    const singleStage: StageDefinition[] = [
      {
        order: 1,
        label: "Manager Approval",
        approver_user_ids: [],
      },
    ];
    render(
      <ApprovalStageStepper
        stages={singleStage}
        currentStage={1}
        totalStages={1}
        status="APPROVED"
        decisions={[sampleDecision(1, "APPROVED", "Ann", "Stock confirmed")]}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText('"Stock confirmed"')).toBeInTheDocument();
  });

  it("shows the approvers count for the current stage when assigned", () => {
    render(
      <ApprovalStageStepper
        stages={[
          {
            order: 1,
            label: "Manager Approval",
            approver_user_ids: ["u-1", "u-2", "u-3"],
          },
          {
            order: 2,
            label: "Director Approval",
            approver_user_ids: [],
          },
        ]}
        currentStage={1}
        totalStages={2}
        status="PENDING"
        decisions={[]}
      />,
      { wrapper: createWrapper() },
    );
    // Three approvers → the _other plural, with the count interpolated.
    expect(screen.getByText("3 approvers assigned")).toBeInTheDocument();
  });

  it("uses an accessible list role for the stage list", () => {
    render(
      <ApprovalStageStepper
        stages={sampleStages}
        currentStage={2}
        totalStages={3}
        status="IN_PROGRESS"
        decisions={[]}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByRole("list")).toBeInTheDocument();
  });

  it("renders currentStage indicator only once even when stages repeat labels", () => {
    const stages: StageDefinition[] = [
      { order: 1, label: "Manager", approver_user_ids: [] },
      {
        order: 2,
        label: "Director Approval",
        approver_user_ids: [],
      },
    ];
    render(
      <ApprovalStageStepper
        stages={stages}
        currentStage={2}
        totalStages={2}
        status="IN_PROGRESS"
        decisions={[]}
      />,
      { wrapper: createWrapper() },
    );
    // The current stage tag is unique — there should be exactly one.
    expect(screen.getAllByText("Current").length).toBe(1);
  });

  it("names a single stage saved without a label by its order", () => {
    render(
      <ApprovalStageStepper
        stages={[{ order: 1, label: "", approver_user_ids: [] }]}
        currentStage={1}
        totalStages={1}
        status="IN_PROGRESS"
        decisions={[]}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("#1")).toBeInTheDocument();
  });

  it("names each unlabelled stage of a multi-stage workflow by its order", () => {
    render(
      <ApprovalStageStepper
        stages={[
          { order: 1, label: "  ", approver_user_ids: [] },
          { order: 2, label: "Director", approver_user_ids: [] },
        ]}
        currentStage={1}
        totalStages={2}
        status="IN_PROGRESS"
        decisions={[]}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("Director")).toBeInTheDocument();
  });
});
