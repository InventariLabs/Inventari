/**
 * A failed sign-in has one sentence for every cause. A reader blocked by the
 * rate limiter must not be told their password is wrong, and neither may a
 * reader with no connection: either would change a password that works.
 */
import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import { loginFailureKey } from "./loginFailure";

const withStatus = (status: number) =>
  new AxiosError("failed", "ERR_BAD_REQUEST", undefined, null, {
    status,
    statusText: "",
    data: {},
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  });

describe("loginFailureKey", () => {
  it("keeps the credentials sentence for a rejected password", () => {
    expect(loginFailureKey(withStatus(401))).toBe("invalidCredentials");
  });

  it("does not blame the password when the limiter says no", () => {
    expect(loginFailureKey(withStatus(429))).toBe("login.tooManyAttempts");
  });

  it("does not blame the password when the server broke", () => {
    expect(loginFailureKey(withStatus(500))).toBe("login.serverError");
    expect(loginFailureKey(withStatus(503))).toBe("login.serverError");
  });

  it("names the connection when the request never arrived", () => {
    expect(
      loginFailureKey(new AxiosError("Network Error", "ERR_NETWORK")),
    ).toBe("login.networkError");
    expect(loginFailureKey(new Error("boom"))).toBe("login.networkError");
  });

  it("falls back to a plain failure for anything else", () => {
    expect(loginFailureKey(withStatus(400))).toBe("login.failed");
  });
});
