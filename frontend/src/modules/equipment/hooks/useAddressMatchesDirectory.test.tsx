/**
 * The two guards the directory check shipped without tests:
 * the lookup waits 400 ms for the typing to settle, and it stays off
 * entirely where no person is being named. Both were measured invisible
 * to the suite before — every CheckoutModal test passed on the
 * per-keystroke, always-on version of the hook, because the
 * shared members endpoint also answers the person picker's own queries
 * and a modal-level request count cannot tell the two apart. These tests
 * mount the hook alone, where every getMembers call is the hook's.
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { organizationsApi } from "@/lib/api/organizations";
import { useAddressMatchesDirectory } from "./useAddressMatchesDirectory";

vi.mock("@/lib/api/organizations", () => ({
  organizationsApi: {
    getMembers: vi.fn(async () => ({
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
    })),
  },
}));

vi.mock("@/modules/equipment/hooks/useEmployeeAutocomplete", () => ({
  useEmployeeAutocomplete: () => ({ data: undefined }),
}));

const mockedGetMembers = vi.mocked(organizationsApi.getMembers);

type HookProps = {
  email: string;
  enabled: boolean;
  partnersEnabled: boolean;
};

function renderAddressHook(
  initial: HookProps = { email: "", enabled: true, partnersEnabled: false },
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook((props) => useAddressMatchesDirectory(props), {
    initialProps: initial,
    wrapper,
  });
}

describe("useAddressMatchesDirectory — the check waits and asks politely", () => {
  it("asks the register once per settled address, not once per keystroke", async () => {
    const view = renderAddressHook();

    // Seventeen keystrokes, one rerender each — every one inside the
    // settle window, so exactly one of them survives the debounce.
    let email = "";
    for (const char of "ghost@example.com") {
      email += char;
      await act(async () => {
        view.rerender({ email, enabled: true, partnersEnabled: false });
      });
    }
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 500));
    });

    expect(mockedGetMembers).toHaveBeenCalledTimes(1);
    expect(mockedGetMembers).toHaveBeenLastCalledWith(
      0,
      20,
      "ghost@example.com",
    );
  });

  it("asks nobody while no person is being named", async () => {
    renderAddressHook({
      email: "ghost@example.com",
      enabled: false,
      partnersEnabled: false,
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 500));
    });
    await waitFor(() => {
      expect(mockedGetMembers).not.toHaveBeenCalled();
    });
  });
});

/**
 * A register that failed to answer is not a register that says the address is
 * nobody's — so the warning stays quiet.
 *
 * Behaviour document, not teeth: a failed request leaves no data either, and
 * `!memberData` already answers the same way the failure flags do, so this
 * passes with those flags dropped from the read. What it pins is the
 * silence: a correct address is never called a typo by a check that does not
 * know.
 */
describe("useAddressMatchesDirectory — a register that did not answer", () => {
  it("does not call a correct address a typo", async () => {
    mockedGetMembers.mockRejectedValueOnce(new Error("boom"));
    const view = renderAddressHook({
      email: "anna@example.com",
      enabled: true,
      partnersEnabled: false,
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 500));
    });

    await waitFor(() => expect(mockedGetMembers).toHaveBeenCalledTimes(1));
    expect(view.result.current.unmatched).toBe(false);
  });
});
