import { AxiosError } from "axios";
import i18n from "i18next";
import { describe, expect, it, vi } from "vitest";
import { scanFailure } from "./toastScanError";

function refusal(status: number, data: unknown): AxiosError {
  return new AxiosError("refused", String(status), undefined, undefined, {
    status,
    statusText: "",
    data,
    headers: {},
    config: {} as never,
  });
}

describe("scanFailure", () => {
  it("offers the search, which opens the list on the code, when nothing recognized it", () => {
    const navigate = vi.fn();

    const failure = scanFailure(
      refusal(404, { detail: { code: "SCAN_UNRECOGNIZED" } }),
      "590 123",
      i18n.t,
      navigate,
    );

    expect(failure.code).toBe("590 123");
    failure.onSearch?.();
    expect(navigate).toHaveBeenCalledWith("/inventory/items?search=590%20123");
  });

  it("tells a scanner past the allowance to wait, with no search to offer", () => {
    const failure = scanFailure(
      refusal(429, { detail: "slow down" }),
      "x",
      i18n.t,
      vi.fn(),
    );

    expect(failure.message).toBe(
      "Too many scans in a minute. Wait a moment, then scan again.",
    );
    expect(failure.onSearch).toBeUndefined();
  });

  it("falls back to the generic sentence for a failure it cannot name", () => {
    const failure = scanFailure(new Error("network"), "x", i18n.t, vi.fn());

    expect(failure.message).toBe("Could not look up the code");
    expect(failure.onSearch).toBeUndefined();
  });
});
