import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { useScanResolver } from "@/hooks/useScanResolver";
import { labelsApi } from "@/lib/api/labels";
import type { LabelScanView } from "@/types";

vi.mock("@/lib/api/labels", () => ({
  labelsApi: { scan: vi.fn() },
}));

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigate };
});

const toastCalls: {
  message: string;
  action?: { label: string; onClick: () => void };
}[] = [];
const toastErrors: string[] = [];
const toastErrorActions: { label?: string; onClick: () => void }[] = [];
const toastDismissed: unknown[] = [];
vi.mock("sonner", () => ({
  toast: Object.assign(
    (
      message: string,
      options?: { action?: { label: string; onClick: () => void } },
    ) => {
      toastCalls.push({ message, action: options?.action });
    },
    {
      error: (
        message: string,
        options?: { action?: { label: string; onClick: () => void } },
      ) => {
        toastErrors.push(message);
        toastErrorActions.push(
          options?.action ?? { label: undefined, onClick: () => {} },
        );
        return `toast-${toastErrors.length}`;
      },
      dismiss: (id: unknown) => toastDismissed.push(id),
      success: vi.fn(),
    },
  ),
}));

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <MemoryRouter>{children}</MemoryRouter>
);

const location: LabelScanView = {
  status: "storage_context",
  label_code: "LOC-7",
  action: "set_storage_context",
  location: { id: "s1", name: "Cold Storage A", icon: "📦" },
};

const axiosError = (code: string, message: string) =>
  Object.assign(new Error(message), {
    isAxiosError: true,
    response: { status: 404, data: { detail: { code, message } } },
  });

beforeEach(() => {
  vi.mocked(labelsApi.scan).mockReset();
  navigate.mockReset();
  toastCalls.length = 0;
  toastErrors.length = 0;
  toastErrorActions.length = 0;
  toastDismissed.length = 0;
});

describe("useScanResolver", () => {
  it("hands a recognized code to the screen before anything else", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue(location);
    const handle = vi.fn().mockReturnValue(true);

    const { result } = renderHook(() => useScanResolver({ handle }), {
      wrapper,
    });
    await act(() => result.current.resolve("LOC-7"));

    expect(handle).toHaveBeenCalledWith(location, "LOC-7");
    expect(toastCalls).toHaveLength(0);
  });

  it("names the thing and offers a way through when the screen declines it", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue(location);

    const { result } = renderHook(
      () => useScanResolver({ handle: () => false }),
      { wrapper },
    );
    await act(() => result.current.resolve("LOC-7"));

    expect(toastCalls).toHaveLength(1);
    expect(toastCalls[0].message).toContain("Cold Storage A");
    toastCalls[0].action?.onClick();
    expect(navigate).toHaveBeenCalledWith("/inventory/locations/s1");
  });

  it("lets a screen accept a code no provider recognized", async () => {
    vi.mocked(labelsApi.scan).mockRejectedValue(
      axiosError("SCAN_UNRECOGNIZED", "Unknown code"),
    );
    const accept = vi.fn().mockReturnValue(true);

    const { result } = renderHook(
      () => useScanResolver({ handle: () => true, acceptUnrecognized: accept }),
      { wrapper },
    );
    await act(() => result.current.resolve("NEW-EAN-123"));

    expect(accept).toHaveBeenCalledWith("NEW-EAN-123");
    expect(toastErrors).toHaveLength(0);
  });

  it("keeps the server's message for a screen that cannot accept one", async () => {
    vi.mocked(labelsApi.scan).mockRejectedValue(
      axiosError("SCAN_UNRECOGNIZED", "Unknown code"),
    );

    const { result } = renderHook(
      () => useScanResolver({ handle: () => true }),
      { wrapper },
    );
    await act(() => result.current.resolve("ZZZ"));

    expect(toastErrors).toEqual(["Unknown code"]);
  });

  it("offers the search with the code in it when nothing recognized it", async () => {
    vi.mocked(labelsApi.scan).mockRejectedValue(
      axiosError("SCAN_UNRECOGNIZED", "Unknown code"),
    );

    const { result } = renderHook(
      () => useScanResolver({ handle: () => true }),
      { wrapper },
    );
    await act(() => result.current.resolve("BRG 6204/A"));

    // Asking again cannot change the answer; the search can.
    expect(toastErrorActions[0].label).toBe("Search for this code");
    toastErrorActions[0].onClick();
    expect(navigate).toHaveBeenCalledWith(
      "/inventory/items?search=BRG%206204%2FA",
    );
  });

  it("says the lookup failed and offers to ask for the same code again", async () => {
    // The reader typed a code correctly and the lookup never came back.
    // "Scanning error" named neither the question that went unanswered nor
    // a way to put it again — the code had to be retyped.
    const serverFailure = Object.assign(new Error("boom"), {
      isAxiosError: true,
      response: { status: 500, data: {} },
    });
    vi.mocked(labelsApi.scan)
      .mockRejectedValueOnce(serverFailure)
      .mockResolvedValueOnce(location);
    const handle = vi.fn().mockReturnValue(true);

    const { result } = renderHook(() => useScanResolver({ handle }), {
      wrapper,
    });
    await act(() => result.current.resolve("LOC-7"));

    expect(toastErrors).toEqual(["Could not look up the code"]);
    expect(toastErrorActions[0].label).toBe("Try again");

    await act(async () => {
      toastErrorActions[0].onClick();
    });

    // The refusal is answered by the attempt, not left standing beside it.
    expect(toastDismissed).toHaveLength(1);
    expect(labelsApi.scan).toHaveBeenCalledTimes(2);
    expect(handle).toHaveBeenCalledWith(location, "LOC-7");
    await waitFor(() => expect(result.current.isResolving).toBe(false));
  });

  it("tells the reader to wait a moment when the lookups ran out", async () => {
    // Past the per-minute allowance the API answers 429 with a generic
    // "try again later"; a scanner has to say what to do right now.
    const refused = Object.assign(new Error("Too many requests"), {
      isAxiosError: true,
      response: {
        status: 429,
        data: {
          detail: {
            code: "RATE_LIMIT_EXCEEDED",
            message: "Too many requests. Try again later.",
          },
        },
      },
    });
    vi.mocked(labelsApi.scan).mockRejectedValue(refused);

    const { result } = renderHook(
      () => useScanResolver({ handle: () => true }),
      { wrapper },
    );
    await act(() => result.current.resolve("LOC-7"));

    expect(toastErrors).toEqual([
      "Too many scans in a minute. Wait a moment, then scan again.",
    ]);
  });

  it("does not queue a second lookup while one is in flight", async () => {
    // The camera fires repeatedly at the same symbol.
    let release: (value: LabelScanView) => void = () => {};
    vi.mocked(labelsApi.scan).mockReturnValue(
      new Promise<LabelScanView>((resolve) => {
        release = resolve;
      }),
    );

    const { result } = renderHook(
      () => useScanResolver({ handle: () => true }),
      { wrapper },
    );
    let first!: Promise<void>;
    await act(async () => {
      first = result.current.resolve("LOC-7");
      await result.current.resolve("LOC-7");
    });
    expect(labelsApi.scan).toHaveBeenCalledTimes(1);

    await act(async () => {
      release(location);
      await first;
    });
    await waitFor(() => expect(result.current.isResolving).toBe(false));
  });

  it("ignores an empty code", async () => {
    const { result } = renderHook(
      () => useScanResolver({ handle: () => true }),
      { wrapper },
    );
    await act(() => result.current.resolve("   "));
    expect(labelsApi.scan).not.toHaveBeenCalled();
  });
});
