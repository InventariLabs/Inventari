import {
  describe,
  expect,
  it,
  vi,
  beforeEach,
  afterEach,
  type Mock,
} from "vitest";
import { render, screen, waitFor } from "@/test/utils";
import userEvent from "@testing-library/user-event";

import { POApprovalSettings } from "./POApprovalSettings";
import * as poHooks from "../hooks/usePurchaseOrders";
import { signInWith, signOut } from "@/test/auth";

vi.mock("../hooks/usePurchaseOrders", () => ({
  usePOSettings: vi.fn(),
  useUpdatePOSettings: vi.fn(),
  usePOApprovalWorkflowConfigured: vi.fn(),
}));

const isModuleEnabled = vi.fn(() => true);
vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  // Only the reader is faked — the provider still has to be the real one,
  // since the shared render helper mounts it.
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({ isModuleEnabled }),
}));

const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const mockedUsePOSettings = vi.mocked(poHooks.usePOSettings);
const mockedUseUpdatePOSettings = vi.mocked(poHooks.useUpdatePOSettings);
const mockedUseIsWorkflowConfigured = vi.mocked(
  poHooks.usePOApprovalWorkflowConfigured,
);

function withWorkflows(workflows: unknown[]) {
  // The warning asks the same one bit the order screen's action asks —
  // the dedicated endpoint's answer, not the (grant-filtered) list.
  mockedUseIsWorkflowConfigured.mockReturnValue(
    workflows.some(
      (workflow) =>
        (workflow as { target_type?: string }).target_type ===
          "purchase_order" && (workflow as { is_active?: boolean }).is_active,
    ),
  );
}

const poWorkflow = {
  id: "wf-1",
  target_type: "purchase_order",
  is_active: true,
};

function arrange(mutateAsync: Mock) {
  mockedUsePOSettings.mockReturnValue({
    data: { approval_threshold: 1000, approval_required: false },
    isLoading: false,
  } as unknown as ReturnType<typeof poHooks.usePOSettings>);
  mockedUseUpdatePOSettings.mockReturnValue({
    mutateAsync,
    isPending: false,
  } as unknown as ReturnType<typeof poHooks.useUpdatePOSettings>);
}

describe("POApprovalSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    isModuleEnabled.mockReturnValue(true);
    withWorkflows([poWorkflow]);
    // The panel writes through PUT /purchase-orders/settings, which the
    // backend answers to purchase_orders:manage. The workflow warning reads
    // the dedicated configured-endpoint, which answers without any grant
    // over approvals.
    signInWith(["purchase_orders:write", "purchase_orders:manage"]);
  });

  afterEach(() => {
    signOut();
  });

  it("checks the threshold before sending it", async () => {
    // The `min="0"` on the input was decorative — nothing enforced it, so a
    // negative threshold went to the server and came back as a raw Pydantic
    // sentence in a toast with no field attached to it.
    const mutateAsync = vi.fn().mockResolvedValue({});
    arrange(mutateAsync);
    const user = userEvent.setup();

    render(<POApprovalSettings />);
    const field = screen.getByLabelText(/threshold/i);
    await user.clear(field);
    await user.type(field, "-500");
    await user.click(screen.getByRole("button", { name: /save/i }));

    expect(mutateAsync).not.toHaveBeenCalled();
    expect(
      await screen.findByText("The threshold cannot be negative."),
    ).toBeInTheDocument();
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveFocus();
  });

  it("puts a rejected threshold on the field, not in a toast", async () => {
    const mutateAsync = vi.fn().mockRejectedValue({
      isAxiosError: true,
      response: {
        data: {
          detail: [
            {
              loc: ["body", "approval_threshold"],
              msg: "Input should be greater than or equal to 0",
              type: "greater_than_equal",
            },
          ],
        },
      },
    });
    arrange(mutateAsync);
    const user = userEvent.setup();

    render(<POApprovalSettings />);
    const field = screen.getByLabelText(/threshold/i);
    await user.clear(field);
    await user.type(field, "250");
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(
      await screen.findByText("Input should be greater than or equal to 0"),
    ).toBeInTheDocument();
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(toastError).not.toHaveBeenCalled();
  });

  it("still toasts a failure that belongs to no field", async () => {
    const mutateAsync = vi.fn().mockRejectedValue({
      isAxiosError: true,
      response: { data: { detail: "Settings are locked" } },
    });
    arrange(mutateAsync);
    const user = userEvent.setup();

    render(<POApprovalSettings />);
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Settings are locked"),
    );
  });

  it("names the threshold field in the banner when only a threshold is set", async () => {
    // arrange() has a threshold saved and the checkbox off: the requirement
    // that is left is the threshold, so "turn the requirement off" would point
    // at a checkbox that already is.
    withWorkflows([]);
    arrange(vi.fn());

    render(<POApprovalSettings />);

    expect(
      await screen.findByText(/or clear the approval threshold/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/turn the requirement off/i)).toBeNull();
  });

  it("sends the threshold it was given", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({});
    arrange(mutateAsync);
    const user = userEvent.setup();

    render(<POApprovalSettings />);
    const field = screen.getByLabelText(/threshold/i);
    await user.clear(field);
    await user.type(field, "2500.50");
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        approval_threshold: 2500.5,
        approval_required: false,
      }),
    );
  });

  it("says the approval setting has nothing behind it, and where to fix that", async () => {
    // The setting used to be an ornament: with no workflow the order confirmed
    // anyway. Confirmation is refused now, so the screen that switched the
    // requirement on has to name the missing piece.
    withWorkflows([]);
    arrange(vi.fn());

    render(<POApprovalSettings />);

    expect(
      await screen.findByText(/Approval is required, but nothing enforces it/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create workflow" }),
    ).toBeInTheDocument();
  });

  it("points at the module store when approvals is off entirely", async () => {
    isModuleEnabled.mockReturnValue(false);
    withWorkflows([]);
    arrange(vi.fn());

    render(<POApprovalSettings />);

    expect(
      await screen.findByText(/The Approvals module is off/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open apps" }),
    ).toBeInTheDocument();
  });

  it("stays quiet once a purchase order workflow exists", () => {
    arrange(vi.fn());

    render(<POApprovalSettings />);

    expect(
      screen.queryByText(/Approval is required, but nothing enforces it/),
    ).not.toBeInTheDocument();
  });

  it("does not offer to save settings it failed to read", async () => {
    // Measured before the fix, with approval_required=true and a threshold of
    // 2500 stored: a 500 on the read drew the switch unticked and the field
    // empty, said nothing, and left Save live. One click turned the
    // requirement off — and the only trace was 'Settings saved'.
    const refetch = vi.fn();
    mockedUsePOSettings.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      refetch,
    } as unknown as ReturnType<typeof poHooks.usePOSettings>);
    mockedUseUpdatePOSettings.mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof poHooks.useUpdatePOSettings>);

    render(<POApprovalSettings />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /save/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/threshold/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(refetch).toHaveBeenCalled();
  });

  describe("behind purchase_orders:manage", () => {
    // Whether an order needs approval is not a buyer's own call: the PUT
    // answers to :manage, and a member holding only :write used to get the
    // whole form and a "Settings saved" for it.
    it.each([
      [
        "a member who may write orders",
        ["purchase_orders:read", "purchase_orders:write"],
        /you can use this, not reconfigure it/i,
      ],
      // A viewer sees no values either, so it gets the same sentence rather
      // than "you can view this" above an empty page.
      [
        "a viewer",
        ["purchase_orders:read"],
        /you can use this, not reconfigure it/i,
      ],
    ])("offers no save surface to %s", async (_who, grants, notice) => {
      signInWith(grants);
      arrange(vi.fn());

      render(<POApprovalSettings />);

      expect(await screen.findByText(notice)).toBeInTheDocument();
      expect(
        screen.getByText(/ask someone who can manage it/i),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /save/i }),
      ).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/threshold/i)).not.toBeInTheDocument();
    });

    it("keeps the form for an account that may manage the module", () => {
      signInWith([
        "purchase_orders:read",
        "purchase_orders:write",
        "purchase_orders:manage",
      ]);
      arrange(vi.fn());

      render(<POApprovalSettings />);

      expect(screen.getByRole("button", { name: /save/i })).toBeInTheDocument();
      expect(
        screen.queryByText(/you can use this, not reconfigure it/i),
      ).not.toBeInTheDocument();
    });
  });
});
