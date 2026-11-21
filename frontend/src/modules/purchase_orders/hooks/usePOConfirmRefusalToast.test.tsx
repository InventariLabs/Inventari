import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { AxiosError, type AxiosResponse } from "axios";

import { usePOConfirmRefusalToast } from "./usePOConfirmRefusalToast";

const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: { error: (...args: unknown[]) => toastError(...args) },
}));

const navigate = vi.fn();
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }));

let canConfigure = false;
vi.mock("@/module-sdk", () => ({
  useHasPermission: () => canConfigure,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function refusal(code: string, message: string) {
  const error = new AxiosError("refused");
  error.response = {
    status: 400,
    data: { detail: { code, message } },
  } as AxiosResponse;
  return error;
}

describe("usePOConfirmRefusalToast", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    canConfigure = false;
  });

  it("keeps the server's sentence for someone who cannot configure workflows", () => {
    const { result } = renderHook(() => usePOConfirmRefusalToast());

    result.current(
      refusal("PO_APPROVAL_WORKFLOW_MISSING", "Ask your administrator."),
    );

    expect(toastError).toHaveBeenCalledWith("Ask your administrator.");
  });

  it("gives the administrator the way to the Create workflow form", () => {
    canConfigure = true;
    const { result } = renderHook(() => usePOConfirmRefusalToast());

    result.current(
      refusal("PO_APPROVAL_WORKFLOW_MISSING", "Ask your administrator."),
    );

    const [message, options] = toastError.mock.calls[0] as [
      string,
      { action: { label: string; onClick: () => void } },
    ];
    expect(message).toBe("approvalWorkflowMissingForAdmin");
    options.action.onClick();
    expect(navigate).toHaveBeenCalledWith(
      "/approvals/workflows?new=1&target=purchase_order",
    );
  });

  it("leaves every other refusal alone, administrator or not", () => {
    canConfigure = true;
    const { result } = renderHook(() => usePOConfirmRefusalToast());

    result.current(refusal("PO_CONFIRM_INVALID_STATUS", "Not a draft."));

    expect(toastError).toHaveBeenCalledWith("Not a draft.");
  });
});
