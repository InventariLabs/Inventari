/**
 * A refusal written for a reader arrives in the language the app
 * is read in. The authenticated client adds Accept-Language in its request
 * interceptor — but the silent refresh deliberately bypasses that
 * interceptor (it must not re-enter the 401 machinery), and its refusal
 * (expired session, revoked refresh token) surfaces in the toasts of the
 * requests it was queueing. So the refresh call has to carry the header by
 * hand; this pins it.
 */
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import i18next from "i18next";
import { server } from "@/test/mocks/server";
import { apiErrorStatus, extractApiError } from "@/lib/errors";
import { api, tokenStore } from "./client";

describe("the silent refresh speaks the app's language", () => {
  it("carries Accept-Language on the refresh call it makes after a 401", async () => {
    await i18next.changeLanguage("pl");
    let refreshLanguage: string | null = null;
    server.use(
      http.get("*/api/v1/things", () =>
        HttpResponse.json(
          { detail: { message: "stale token" } },
          {
            status: 401,
          },
        ),
      ),
      http.post("*/api/v1/auth/refresh", ({ request }) => {
        refreshLanguage = request.headers.get("Accept-Language");
        return HttpResponse.json({ access_token: "fresh-token" });
      }),
    );
    tokenStore.set("expired-token");

    // First GET answers 401 → silent refresh fires → the retry answers 401
    // again and the guarded _retry stops the loop: the call rejects, the
    // refresh has already been observed.
    await api.get("/things").catch(() => undefined);

    expect(refreshLanguage).toBe("pl");
    tokenStore.clear();
    await i18next.changeLanguage("en");
  });
});

describe("a refused sign-in is not a session to refresh", () => {
  it("does not fire the silent refresh for a 401 on /auth/login", async () => {
    let refreshes = 0;
    server.use(
      http.post("*/api/v1/auth/login", () =>
        HttpResponse.json({ detail: "invalid credentials" }, { status: 401 }),
      ),
      http.post("*/api/v1/auth/refresh", () => {
        refreshes += 1;
        return HttpResponse.json({ access_token: "fresh-token" });
      }),
    );

    const status = await api.post("/auth/login", {}).then(
      () => "resolved",
      (e: unknown) => apiErrorStatus(e),
    );

    // The form's own 401 reaches the form; the probe it used to trigger
    // both doubled the failed requests and replaced the sentence.
    expect(status).toBe(401);
    expect(refreshes).toBe(0);
  });
});

describe("a refresh that answers 204 has no session to give", () => {
  it("clears the token and ends the session", async () => {
    const dispatchSpy = vi.spyOn(window, "dispatchEvent");
    server.use(
      http.get("*/api/v1/things", () =>
        HttpResponse.json({ detail: "stale token" }, { status: 401 }),
      ),
      http.post(
        "*/api/v1/auth/refresh",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    tokenStore.set("expired-token");

    await api.get("/things").catch(() => undefined);

    expect(tokenStore.get()).toBeNull();
    expect(dispatchSpy.mock.calls.some(([e]) => e.type === "auth:logout")).toBe(
      true,
    );
    dispatchSpy.mockRestore();
  });
});

describe("a silent refresh that never got an answer is an outage, not a logout", () => {
  it("keeps the token when the refresh call dies unanswered", async () => {
    const dispatchSpy = vi.spyOn(window, "dispatchEvent");
    server.use(
      http.get("*/api/v1/things", () =>
        HttpResponse.json({ detail: "stale token" }, { status: 401 }),
      ),
      http.post("*/api/v1/auth/refresh", () => HttpResponse.error()),
    );
    tokenStore.set("token-that-may-still-be-good");

    await api.get("/things").catch(() => undefined);

    // The server never answered the refresh: the credential may still be
    // good the moment it returns, so the session is not torn down.
    expect(tokenStore.get()).toBe("token-that-may-still-be-good");
    expect(dispatchSpy.mock.calls.some(([e]) => e.type === "auth:logout")).toBe(
      false,
    );
    dispatchSpy.mockRestore();
  });

  it("the server's own refusal still ends the session", async () => {
    const dispatchSpy = vi.spyOn(window, "dispatchEvent");
    server.use(
      http.get("*/api/v1/things", () =>
        HttpResponse.json({ detail: "stale token" }, { status: 401 }),
      ),
      http.post("*/api/v1/auth/refresh", () =>
        HttpResponse.json({ detail: "revoked" }, { status: 400 }),
      ),
    );
    tokenStore.set("expired-token");

    await api.get("/things").catch(() => undefined);

    expect(tokenStore.get()).toBeNull();
    expect(dispatchSpy.mock.calls.some(([e]) => e.type === "auth:logout")).toBe(
      true,
    );
    dispatchSpy.mockRestore();
  });
});

describe("a refresh failure that is the server's own error", () => {
  it.each([500, 502, 503])(
    "keeps the token when the refresh answers %i",
    async (status) => {
      const dispatchSpy = vi.spyOn(window, "dispatchEvent");
      server.use(
        http.get("*/api/v1/things", () =>
          HttpResponse.json({ detail: "stale token" }, { status: 401 }),
        ),
        http.post(
          "*/api/v1/auth/refresh",
          () => new HttpResponse(null, { status }),
        ),
      );
      tokenStore.set("token-that-may-still-be-good");

      const rejected = await api.get("/things").then(
        () => null,
        (e: unknown) => apiErrorStatus(e),
      );

      // The shapes an outage actually arrives in: the backend's own unhandled
      // error as 500, the proxy in front of it as 502/503 — the production
      // shape the no-response test above could not name. None of them is the
      // server saying the credential is bad, so the token stays.
      expect(rejected).toBe(status);
      expect(tokenStore.get()).toBe("token-that-may-still-be-good");
      expect(
        dispatchSpy.mock.calls.some(([e]) => e.type === "auth:logout"),
      ).toBe(false);
      tokenStore.clear();
      dispatchSpy.mockRestore();
    },
  );
});

describe("a 401 against a refresh that keeps failing", () => {
  it("makes one refresh attempt per request and coalesces a burst", async () => {
    let refreshes = 0;
    let asks = 0;
    server.use(
      http.get("*/api/v1/things", () => {
        asks += 1;
        return HttpResponse.json({ detail: "stale token" }, { status: 401 });
      }),
      http.post("*/api/v1/auth/refresh", () => {
        refreshes += 1;
        return new HttpResponse(null, { status: 503 });
      }),
    );
    tokenStore.set("stale-token");

    const burst = await Promise.all(
      ["a", "b", "c"].map(() =>
        api.get("/things").then(
          () => "resolved",
          (e: unknown) => apiErrorStatus(e),
        ),
      ),
    );

    // Three requests arriving together wait on the one refresh already in
    // flight — the failure is asked about once for the whole burst.
    expect(burst).toEqual([503, 503, 503]);
    expect(refreshes).toBe(1);
    expect(asks).toBe(3);

    // The next request does probe again — but once: `_retry` guards each
    // request from re-entering the refresh it already asked for, and a request
    // that fails is not re-sent, so the probe rate is the app's request rate,
    // not a loop the client drives by itself. The token stays, because the
    // 503 never answered the question.
    const next = await api.get("/things").then(
      () => "resolved",
      (e: unknown) => apiErrorStatus(e),
    );
    expect(next).toBe(503);
    expect(refreshes).toBe(2);
    expect(asks).toBe(4);
    expect(tokenStore.get()).toBe("stale-token");
    tokenStore.clear();
  });
});

describe("a session that ended under a request says so", () => {
  const sentence = () => i18next.t("common:errors.sessionEnded");

  it.each([
    ["answers 204", () => new HttpResponse(null, { status: 204 })],
    [
      "is refused with 401",
      () => HttpResponse.json({ detail: "revoked" }, { status: 401 }),
    ],
  ])(
    "reads as the session's end, not a generic failure, when the refresh %s",
    async (_name, refreshAnswer) => {
      server.use(
        http.post("*/api/v1/things", () =>
          HttpResponse.json({ detail: "stale token" }, { status: 401 }),
        ),
        http.post("*/api/v1/auth/refresh", refreshAnswer),
      );
      tokenStore.set("expired-token");

      const message = await api.post("/things", {}).then(
        () => null,
        (e: unknown) => extractApiError(e, "Failed to add"),
      );

      expect(message).toBe(sentence());
      expect(message).not.toBe("Failed to add");
    },
  );

  it("does not tell a read that it saved nothing", async () => {
    server.use(
      http.get("*/api/v1/things", () =>
        HttpResponse.json({ detail: "stale token" }, { status: 401 }),
      ),
      http.post("*/api/v1/things", () =>
        HttpResponse.json({ detail: "stale token" }, { status: 401 }),
      ),
      http.post(
        "*/api/v1/auth/refresh",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    tokenStore.set("expired-token");

    const read = await api.get("/things").then(
      () => null,
      (e: unknown) => extractApiError(e, "Failed to load"),
    );
    tokenStore.set("expired-token");
    const write = await api.post("/things", {}).then(
      () => null,
      (e: unknown) => extractApiError(e, "Failed to add"),
    );

    expect(read).toBe(i18next.t("common:errors.sessionEndedRead"));
    expect(write).toBe(sentence());
    expect(read).not.toBe(write);
  });

  it("hands a request queued behind the refresh the session's end, not the refresh's raw refusal", async () => {
    server.use(
      http.get("*/api/v1/things", () =>
        HttpResponse.json({ detail: "stale token" }, { status: 401 }),
      ),
      http.get("*/api/v1/others", () =>
        HttpResponse.json({ detail: "stale token" }, { status: 401 }),
      ),
      http.post("*/api/v1/auth/refresh", async () => {
        await new Promise((resolve) => setTimeout(resolve, 20));
        return HttpResponse.json({ detail: "raw refusal" }, { status: 401 });
      }),
    );
    tokenStore.set("expired-token");

    const [first, queued] = await Promise.all(
      ["/things", "/others"].map((url) =>
        api.get(url).then(
          () => null,
          (e: unknown) => extractApiError(e, "Failed to load"),
        ),
      ),
    );

    expect(first).toBe(i18next.t("common:errors.sessionEndedRead"));
    expect(queued).toBe(i18next.t("common:errors.sessionEndedRead"));
  });

  it.each([
    ["answers 204", () => new HttpResponse(null, { status: 204 })],
    [
      "is refused with 401",
      () => HttpResponse.json({ detail: "revoked" }, { status: 401 }),
    ],
  ])(
    "announces the sign-out once when the refresh %s",
    async (_name, refreshAnswer) => {
      server.use(
        http.get("*/api/v1/things", () =>
          HttpResponse.json({ detail: "stale token" }, { status: 401 }),
        ),
        http.post("*/api/v1/auth/refresh", refreshAnswer),
      );
      tokenStore.set("expired-token");
      let logouts = 0;
      const count = () => {
        logouts += 1;
      };
      window.addEventListener("auth:logout", count);
      try {
        await api.get("/things").catch(() => null);
      } finally {
        window.removeEventListener("auth:logout", count);
      }

      expect(logouts).toBe(1);
      expect(tokenStore.get()).toBeNull();
    },
  );
});
