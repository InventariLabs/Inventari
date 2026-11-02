import { describe, it, expect } from "vitest";
import { AxiosError, AxiosHeaders } from "axios";
import { demoSandboxFailure } from "./demoSandboxFailure";

const refusal = (status: number, data: unknown = {}) =>
  new AxiosError("failed", "ERR_BAD_REQUEST", undefined, null, {
    status,
    statusText: "",
    data,
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  });

describe("demoSandboxFailure", () => {
  it("tells the day's cap apart from one address asking too often", () => {
    // Both are 429: the cap is the demo's, the address limit the visitor's.
    expect(
      demoSandboxFailure(
        refusal(429, { detail: { code: "DEMO_SANDBOX_CAP_REACHED" } }),
      ),
    ).toBe("capReached");
    expect(demoSandboxFailure(refusal(429))).toBe("tooManyFromHere");
  });

  it("names an empty pool as a short wait", () => {
    expect(
      demoSandboxFailure(
        refusal(503, { detail: { code: "DEMO_SANDBOX_POOL_EMPTY" } }),
      ),
    ).toBe("poolEmpty");
  });

  it("falls back to a plain failure, and to the network line with no answer", () => {
    expect(demoSandboxFailure(refusal(500))).toBe("failed");
    expect(demoSandboxFailure(new Error("offline"))).toBe("network");
  });
});
