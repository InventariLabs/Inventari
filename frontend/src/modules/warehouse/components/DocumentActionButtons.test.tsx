import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DocumentActionButtons } from "./DocumentActionButtons";
import { tFor } from "@/test/mocks/i18n";

// The component asks for the permissions the API checks, so the spec grants
// them rather than naming a role. `warehouse:manage` is what guards cancel and
// delete on the server; `warehouse:write` is what guards the rest.
const mockAuthState: {
  user: { role: string; is_superuser: boolean; permissions: string[] } | null;
} = {
  user: {
    role: "user",
    is_superuser: false,
    permissions: ["warehouse:read", "warehouse:write", "warehouse:manage"],
  },
};

function grant(...permissions: string[]) {
  mockAuthState.user = { role: "user", is_superuser: false, permissions };
}

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof mockAuthState) => unknown) =>
    selector ? selector(mockAuthState) : mockAuthState,
}));

const t = tFor("warehouse");

const baseProps = {
  isDraft: true,
  isConfirmed: false,
  docStatus: "DRAFT",
  docType: "IN",
  isApplyCorrectionPending: false,
  isCompletePending: false,
  isPdfDownloading: false,
  canStartPicking: false,
  canStartReceiving: false,
  onApplyCorrection: vi.fn(),
  onEdit: vi.fn(),
  onConfirm: vi.fn(),
  onPostNow: vi.fn(),
  onCancel: vi.fn(),
  onDelete: vi.fn(),
  onExecute: vi.fn(),
  onNewCorrection: vi.fn(),
  onReturn: vi.fn(),
  onDownloadPdf: vi.fn(),
  t,
};

describe("DocumentActionButtons permission gating", () => {
  beforeEach(() => {
    grant("warehouse:read", "warehouse:write", "warehouse:manage");
  });

  it("shows cancel and delete to an account holding warehouse:manage", () => {
    render(<DocumentActionButtons {...baseProps} />);
    expect(screen.getByText("Cancel document")).toBeInTheDocument();
    expect(screen.getByText("Delete")).toBeInTheDocument();
  });

  it("shows them to an admin, whose bypass still holds", () => {
    mockAuthState.user = {
      role: "admin",
      is_superuser: false,
      permissions: [],
    };
    render(<DocumentActionButtons {...baseProps} />);
    expect(screen.getByText("Cancel document")).toBeInTheDocument();
    expect(screen.getByText("Delete")).toBeInTheDocument();
  });

  it("hides cancel and delete without warehouse:manage", () => {
    grant("warehouse:read", "warehouse:write");
    render(<DocumentActionButtons {...baseProps} />);
    expect(screen.queryByText("Cancel document")).not.toBeInTheDocument();
    expect(screen.queryByText("Delete")).not.toBeInTheDocument();
    expect(screen.getByText("Edit")).toBeInTheDocument();
    expect(screen.getByText("Receive stock")).toBeInTheDocument();
  });

  it("hides delete on a draft correction without warehouse:manage", () => {
    grant("warehouse:read", "warehouse:write");
    render(<DocumentActionButtons {...baseProps} docType="CORRECTION" />);
    expect(screen.queryByText("Delete")).not.toBeInTheDocument();
    expect(screen.getByText("Apply correction")).toBeInTheDocument();
  });

  it("keeps Apply correction on a CONFIRMED correction for retry", () => {
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        isConfirmed={true}
        docStatus="CONFIRMED"
        docType="CORRECTION"
      />,
    );
    expect(screen.getByText("Apply correction")).toBeInTheDocument();
  });

  it("offers Cancel on a stuck CONFIRMED correction to a manager of documents", async () => {
    const onCancel = vi.fn();
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        isConfirmed={true}
        docStatus="CONFIRMED"
        docType="CORRECTION"
        onCancel={onCancel}
      />,
    );
    const button = screen.getByRole("button", { name: "Cancel" });
    await userEvent.click(button);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("hides Cancel on a CONFIRMED correction without warehouse:manage", () => {
    grant("warehouse:read", "warehouse:write");
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        isConfirmed={true}
        docStatus="CONFIRMED"
        docType="CORRECTION"
      />,
    );
    expect(screen.getByText("Apply correction")).toBeInTheDocument();
    expect(screen.queryByText("Cancel")).not.toBeInTheDocument();
  });
});

/**
 * The statuses the API will cancel a document in, and therefore the statuses
 * the screen has to offer it in.
 *
 * ``cancel_document`` in ``_document_workflow_transitions.py`` accepts DRAFT,
 * PENDING_APPROVAL and CONFIRMED and refuses the rest; a backend test pins
 * that set and points back here. The screen used to offer the action on a
 * draft alone, so a document that stuck at execution held its reservation on
 * the whole shelf with no way out of it for anybody.
 */
const CANCELLABLE = ["DRAFT", "PENDING_APPROVAL", "CONFIRMED"];

describe("DocumentActionButtons cancel reaches every status the API cancels", () => {
  beforeEach(() => {
    grant("warehouse:read", "warehouse:write", "warehouse:manage");
  });

  it.each(CANCELLABLE)(
    "offers cancel on %s to a manager",
    async (docStatus) => {
      const onCancel = vi.fn();
      render(
        <DocumentActionButtons
          {...baseProps}
          isDraft={docStatus === "DRAFT"}
          isConfirmed={docStatus === "CONFIRMED"}
          docStatus={docStatus}
          onCancel={onCancel}
        />,
      );
      await userEvent.click(
        screen.getByRole("button", { name: "Cancel document" }),
      );
      expect(onCancel).toHaveBeenCalledTimes(1);
    },
  );

  it("does not offer it once the document is completed", () => {
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        isConfirmed={false}
        docStatus="COMPLETED"
      />,
    );
    expect(screen.queryByText("Cancel document")).not.toBeInTheDocument();
  });

  it("tells a write-only account who can do it instead", () => {
    grant("warehouse:read", "warehouse:write");
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        isConfirmed={true}
        docStatus="CONFIRMED"
      />,
    );
    const button = screen.getByRole("button", { name: "Cancel document" });
    expect(button).toBeDisabled();
    expect(button.parentElement).toHaveAttribute(
      "title",
      "Cancelling a confirmed document releases the stock it holds \u2014 ask someone who can manage documents.",
    );
  });

  it("says nothing about it to an account that cannot write either", () => {
    grant("warehouse:read");
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        isConfirmed={true}
        docStatus="CONFIRMED"
      />,
    );
    expect(screen.queryByText("Cancel document")).not.toBeInTheDocument();
  });
});

describe("DocumentActionButtons WMS actions", () => {
  beforeEach(() => {
    grant("warehouse:read", "warehouse:write", "warehouse:manage");
  });

  const confirmedProps = {
    ...baseProps,
    isDraft: false,
    isConfirmed: true,
    docStatus: "CONFIRMED",
  };

  beforeEach(() => {
    grant("warehouse:read", "warehouse:write", "warehouse:manage");
  });

  it("offers picking once the document is confirmed and picking is possible", async () => {
    const onStartPicking = vi.fn();
    render(
      <DocumentActionButtons
        {...confirmedProps}
        canStartPicking
        onStartPicking={onStartPicking}
      />,
    );

    const button = screen.getByRole("button", {
      name: "Scan picking",
    });
    expect(button).toBeEnabled();

    await userEvent.click(button);
    expect(onStartPicking).toHaveBeenCalledTimes(1);
  });

  it("disables picking while an approval request is pending", async () => {
    const onStartPicking = vi.fn();
    render(
      <DocumentActionButtons
        {...confirmedProps}
        canStartPicking
        hasPendingApproval
        onStartPicking={onStartPicking}
      />,
    );

    const button = screen.getByRole("button", {
      name: "Scan picking",
    });
    expect(button).toBeDisabled();
    expect(button.parentElement).toHaveAttribute(
      "title",
      "Waiting for approval \u2014 execution is blocked until the request is resolved.",
    );

    await userEvent.click(button);
    expect(onStartPicking).not.toHaveBeenCalled();
  });

  it("hides picking when the document cannot be picked", () => {
    render(
      <DocumentActionButtons
        {...confirmedProps}
        canStartPicking={false}
        onStartPicking={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", {
        name: "Scan picking",
      }),
    ).toBeNull();
  });

  it("offers receiving once the document is confirmed and receiving is possible", async () => {
    const onStartReceiving = vi.fn();
    render(
      <DocumentActionButtons
        {...confirmedProps}
        canStartReceiving
        onStartReceiving={onStartReceiving}
      />,
    );

    const button = screen.getByRole("button", {
      name: "Scan receiving",
    });
    expect(button).toBeEnabled();

    await userEvent.click(button);
    expect(onStartReceiving).toHaveBeenCalledTimes(1);
  });

  it("disables receiving while an approval request is pending", () => {
    render(
      <DocumentActionButtons
        {...confirmedProps}
        canStartReceiving
        hasPendingApproval
        onStartReceiving={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", {
        name: "Scan receiving",
      }),
    ).toBeDisabled();
  });

  it("disables execution and says why when approval is required but no request is open", () => {
    render(
      <DocumentActionButtons
        {...confirmedProps}
        canStartReceiving
        approvalRequiredNoRequest
        onStartReceiving={vi.fn()}
      />,
    );

    const button = screen.getByRole("button", { name: "Scan receiving" });
    expect(button).toBeDisabled();
    expect(button.parentElement).toHaveAttribute(
      "title",
      expect.stringContaining("request approval first"),
    );
  });
});

describe("DocumentActionButtons naming", () => {
  beforeEach(() => {
    grant("warehouse:read", "warehouse:write", "warehouse:manage");
  });

  it("names the document action, not just 'Cancel'", () => {
    // The confirm dialog's own Cancel means "do not confirm"; this one
    // cancels the document. Two buttons of the same name on one screen, with
    // opposite meanings.
    render(<DocumentActionButtons {...baseProps} />);
    expect(screen.getByText("Cancel document")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Cancel$/ }),
    ).not.toBeInTheDocument();
  });

  it("says what the inline execution does, per document type", () => {
    // "Receive stock" and "Execute" sat side by side meaning the same thing
    // to the reader. The inline path takes the document type's verb...
    const { rerender } = render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        isConfirmed
        docStatus="CONFIRMED"
        docType="IN"
      />,
    );
    expect(screen.getByText("Receive stock")).toBeInTheDocument();
    expect(screen.queryByText("Execute")).not.toBeInTheDocument();

    rerender(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        isConfirmed
        docStatus="CONFIRMED"
        docType="OUT"
      />,
    );
    expect(screen.getByText("Pick items")).toBeInTheDocument();

    // A scrap is executed by writing the goods off; nothing is picked for
    // anybody, and the button said "Pick items" all the same.
    rerender(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        isConfirmed
        docStatus="CONFIRMED"
        docType="SCRAP"
      />,
    );
    expect(screen.getByText("Write off stock")).toBeInTheDocument();
    expect(screen.queryByText("Pick items")).not.toBeInTheDocument();
  });

  it.each(["IN", "OUT", "INT"])(
    "offers a return on a completed %s, as the API takes one",
    (docType) => {
      // The server returns receipts, deliveries and transfers; the screen
      // offered the button on the last two only, so goods sent back to a
      // supplier had no way in but the API.
      render(
        <DocumentActionButtons
          {...baseProps}
          isDraft={false}
          docStatus="COMPLETED"
          docType={docType}
        />,
      );
      expect(screen.getByText("Create return")).toBeInTheDocument();
    },
  );

  it.each(["INTERNAL_IN", "INTERNAL_OUT", "SCRAP"])(
    "offers no return on a completed %s, which the API refuses",
    (docType) => {
      render(
        <DocumentActionButtons
          {...baseProps}
          isDraft={false}
          docStatus="COMPLETED"
          docType={docType}
        />,
      );
      expect(screen.queryByText("Create return")).not.toBeInTheDocument();
    },
  );

  it("offers no return on a document Undo has put back in full", () => {
    // The server would refuse it: nothing is left of any line to send back.
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        docStatus="COMPLETED"
        docType="OUT"
        isReversed
      />,
    );
    expect(screen.queryByText("Create return")).not.toBeInTheDocument();
  });

  it("marks the scanner path as scanning, in outline", () => {
    // ...and the WMS session takes a Scan prefix, so the two names carry
    // their difference instead of colliding.
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        isConfirmed
        docStatus="CONFIRMED"
        docType="IN"
        canStartReceiving
        onStartReceiving={vi.fn()}
      />,
    );
    expect(screen.getByText("Scan receiving")).toBeInTheDocument();
    expect(screen.getByText("Receive stock")).toBeInTheDocument();
  });

  it("leaves the new-correction action to the corrections section", () => {
    // It was offered twice under one name: header bar and the Corrections
    // card right below it.
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        docStatus="COMPLETED"
        docType="IN"
      />,
    );
    expect(screen.queryByText("New correction")).not.toBeInTheDocument();
  });
});

describe("DocumentActionButtons one-step posting", () => {
  beforeEach(() => {
    grant("warehouse:read", "warehouse:write", "warehouse:manage");
  });

  it.each([
    ["IN", "Receive stock"],
    ["INTERNAL_IN", "Receive stock"],
    ["OUT", "Issue stock"],
    ["INT", "Move stock"],
    ["INTERNAL_OUT", "Remove from stock"],
    ["SCRAP", "Write off stock"],
    ["ADJUSTMENT", "Adjust stock"],
  ])("offers the one-step %s action under its own verb", (docType, label) => {
    const onPostNow = vi.fn();
    render(
      <DocumentActionButtons
        {...baseProps}
        docType={docType}
        onPostNow={onPostNow}
      />,
    );
    const button = screen.getByRole("button", { name: label });
    expect(button).toBeInTheDocument();
    // The two-step confirm is not the draft's primary action any more, and
    // without a future date there is no plan to make either.
    expect(
      screen.queryByRole("button", { name: "Confirm" }),
    ).not.toBeInTheDocument();
    return userEvent.click(button).then(() => {
      expect(onPostNow).toHaveBeenCalledTimes(1);
    });
  });

  it("says 'Send for approval' when the profile requires one", () => {
    render(
      <DocumentActionButtons {...baseProps} docType="OUT" approvalRequired />,
    );
    expect(
      screen.getByRole("button", { name: "Send for approval" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Issue stock" }),
    ).not.toBeInTheDocument();
  });

  it("leaves the confirm step in the menu as 'Plan' for a future date", async () => {
    const onConfirm = vi.fn();
    render(
      <DocumentActionButtons
        {...baseProps}
        isPlanned
        onConfirm={onConfirm}
        onPostNow={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Receive stock" }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    const plan = screen.getByRole("button", { name: "Plan" });
    await userEvent.click(plan);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});

describe("DocumentActionButtons without an approval workflow", () => {
  it("names the missing workflow when approval is required and cannot be requested", () => {
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        isConfirmed
        docStatus="CONFIRMED"
        approvalRequiredNoRequest
        approvalWorkflowMissing
      />,
    );
    const button = screen.getByRole("button", { name: "Receive stock" });
    expect(button).toBeDisabled();
    expect(button.parentElement).toHaveAttribute(
      "title",
      expect.stringContaining("no approval workflow is active"),
    );
  });
});

describe("DocumentActionButtons undo", () => {
  beforeEach(() => {
    grant("warehouse:read", "warehouse:write", "warehouse:manage");
  });

  it("offers the receipt's own undo verb on a completed receipt", async () => {
    const onUndo = vi.fn();
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        docStatus="COMPLETED"
        docType="IN"
        canUndo
        onUndo={onUndo}
      />,
    );
    const button = screen.getByRole("button", { name: "Undo receipt" });
    await userEvent.click(button);
    expect(onUndo).toHaveBeenCalledTimes(1);
  });

  it("names the issue and the move in their own words", () => {
    const { unmount } = render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        docStatus="COMPLETED"
        docType="OUT"
        canUndo
        onUndo={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Undo issue" }),
    ).toBeInTheDocument();
    unmount();
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        docStatus="COMPLETED"
        docType="INT"
        canUndo
        onUndo={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Undo move" }),
    ).toBeInTheDocument();
  });

  it("does not offer undo where later movements may have used the stock", () => {
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        docStatus="COMPLETED"
        docType="IN"
        canUndo={false}
        onUndo={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Undo receipt" }),
    ).not.toBeInTheDocument();
  });

  it("keeps undo away from a correction", () => {
    render(
      <DocumentActionButtons
        {...baseProps}
        isDraft={false}
        docStatus="COMPLETED"
        docType="CORRECTION"
        canUndo
        onUndo={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Undo receipt" }),
    ).not.toBeInTheDocument();
  });
});
