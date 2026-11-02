import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@/test/utils";

import { DocumentApprovalSetupNoticeSlot } from "./DocumentApprovalSetupNoticeSlot";
import { useApprovalWorkflows } from "@/modules/approvals/hooks/useApprovalWorkflows";
import { signInWith, signOut } from "@/test/auth";

vi.mock("@/modules/approvals/hooks/useApprovalWorkflows", () => ({
  useApprovalWorkflows: vi.fn(),
}));

const mockedUseApprovalWorkflows = vi.mocked(useApprovalWorkflows);

function withWorkflows(workflows: unknown[]) {
  mockedUseApprovalWorkflows.mockReturnValue({
    data: workflows,
    isLoading: false,
  } as unknown as ReturnType<typeof useApprovalWorkflows>);
}

const documentWorkflow = {
  id: "wf-1",
  target_type: "document",
  is_active: true,
};

function renderNotice(approvalRequested: boolean) {
  return render(
    <DocumentApprovalSetupNoticeSlot data={{ approvalRequested }} />,
  );
}

const NOTHING_ENFORCES_IT = /Approval is required, but nothing enforces it/;

describe("DocumentApprovalSetupNoticeSlot", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    withWorkflows([documentWorkflow]);
    // The notice reads the workflow list, which the server filters to
    // approvals:read — only an account holding the grant may conclude
    // "nothing enforces it" from an empty list.
    signInWith(["approvals:read"]);
  });

  afterEach(() => {
    signOut();
  });

  it("names the workflow half of the approval rule, not only the profile half", () => {
    // An empty profile with an active document workflow parks every
    // confirmed document on its own.
    renderNotice(false);

    expect(screen.getByTestId("approval-consequence")).toHaveTextContent(
      /active document workflow makes every confirmed document wait/i,
    );
  });

  it("says the approval setting has nothing behind it, and where to fix that", async () => {
    // The setting used to be an ornament: with no workflow the document
    // confirmed anyway. Confirmation is refused now, so the screen that
    // switched the requirement on has to name the missing piece.
    withWorkflows([]);
    renderNotice(true);

    expect(await screen.findByText(NOTHING_ENFORCES_IT)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create workflow" }),
    ).toBeInTheDocument();
  });

  it("stays quiet about a missing workflow once one exists", () => {
    renderNotice(true);

    expect(screen.queryByText(NOTHING_ENFORCES_IT)).not.toBeInTheDocument();
  });

  it("stays quiet for an account that cannot read the workflow list", () => {
    // Without approvals:read the server answers the list with a filtered,
    // always-empty 200 — the notice cannot tell "nothing configured" from
    // "nothing visible", so it raises no warning.
    signInWith([]);
    withWorkflows([]);
    renderNotice(true);

    expect(screen.queryByText(NOTHING_ENFORCES_IT)).not.toBeInTheDocument();
  });

  // The combination matrix: what is configured (asked for approval or not)
  // x whether a document workflow exists. The sentence is the server rule in
  // the reader's terms.
  describe("the consequence for the configured combination", () => {
    it("a profile that names what needs approval, under a workflow, gates only that", () => {
      renderNotice(true);

      expect(screen.getByTestId("approval-consequence")).toHaveTextContent(
        /listed types or above the threshold wait for approval; all others confirm directly/i,
      );
    });

    it("a profile that names what needs approval, with no workflow, says the refusal out loud", () => {
      withWorkflows([]);
      renderNotice(true);

      expect(screen.getByTestId("approval-consequence")).toHaveTextContent(
        /refused at confirmation until an approval workflow exists; all others confirm directly/i,
      );
      expect(screen.getByText(NOTHING_ENFORCES_IT)).toBeInTheDocument();
    });

    it("a silent profile with no workflow lets confirmed documents run", () => {
      withWorkflows([]);
      renderNotice(false);

      expect(screen.getByTestId("approval-consequence")).toHaveTextContent(
        /no document workflow exists, so confirmed documents execute directly/i,
      );
    });

    it("without the workflow read grant it states the requirement, not the outcome", () => {
      // The list answers empty to accounts without approvals:read, so the
      // workflow half is unknowable — the sentence names what the profile
      // asks without claiming whether a workflow is there.
      signInWith([]);
      withWorkflows([]);
      renderNotice(true);

      expect(screen.getByTestId("approval-consequence")).toHaveTextContent(
        /listed types or above the threshold need approval, which a document workflow has to carry out/i,
      );
    });
  });
});
