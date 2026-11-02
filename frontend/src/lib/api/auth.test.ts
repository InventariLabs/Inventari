/**
 * The sign-in, registration and password calls say what the backend reads.
 *
 * A wrong path or a renamed field here does not fail loudly: a registration
 * request that posts `full_name` as `name` still returns 200 from a
 * permissive route and the administrator sees a nameless request. The tests
 * pin verb, path and body, and the one answer that is not the response's
 * data (a 204 refresh is "no session", not an error).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { api, tokenStore } from "./client";
import { authApi } from "./auth";

interface Seen {
  method: string;
  path: string;
  body: unknown;
}

type Verb = "get" | "post" | "patch";

function stub(
  verb: Verb,
  path: string,
  reply: JsonBodyType = {},
  status = 200,
): Seen[] {
  const seen: Seen[] = [];
  server.use(
    http[verb](`*/api/v1${path}`, async ({ request }) => {
      const text = await request.text();
      seen.push({
        method: request.method,
        path: new URL(request.url).pathname,
        body: text ? JSON.parse(text) : undefined,
      });
      return status === 204
        ? new HttpResponse(null, { status })
        : HttpResponse.json(reply, { status });
    }),
  );
  return seen;
}

afterEach(() => {
  vi.restoreAllMocks();
  tokenStore.clear();
});

describe("signing in", () => {
  it("posts the credentials as a form, so the backend's OAuth form reads username and password", async () => {
    const tokens = { access_token: "a", token_type: "bearer" };
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: tokens });

    expect(
      await authApi.login({ username: "ann@example.com", password: "pw" }),
    ).toEqual(tokens);

    const form = post.mock.calls[0][1] as FormData;
    expect(post.mock.calls[0][0]).toBe("/auth/login");
    expect(form.get("username")).toBe("ann@example.com");
    expect(form.get("password")).toBe("pw");
  });

  it("opens the demo sandbox with the visitor's language, so a new account is not created in the wrong one", async () => {
    const seen = stub("post", "/demo/sandbox", { access_token: "t" });

    await authApi.openDemoSandbox(true, "pl");

    expect(seen[0].body).toEqual({ fresh: true, preferred_language: "pl" });
  });

  it("reads the signed-in user and the installation's state", async () => {
    stub("get", "/auth/me", { id: "u1" });
    stub("get", "/auth/init-status", { has_users: true });

    expect(await authApi.getMe()).toEqual({ id: "u1" });
    expect(await authApi.getInitStatus()).toEqual({ has_users: true });
  });

  it("answers null when the refresh endpoint says there is no session, instead of an empty token", async () => {
    stub("post", "/auth/refresh", undefined, 204);
    expect(await authApi.refresh()).toBeNull();

    stub("post", "/auth/refresh", {
      access_token: "new",
      token_type: "bearer",
    });
    expect(await authApi.refresh()).toEqual({
      access_token: "new",
      token_type: "bearer",
    });
  });

  it("forgets the access token on logout, so the next request does not carry a dead session", async () => {
    tokenStore.set("secret");
    const seen = stub("post", "/auth/logout", undefined, 204);

    await authApi.logout();

    expect(seen).toHaveLength(1);
    expect(tokenStore.get()).toBeNull();
  });

  it("reads the version from the unversioned root", async () => {
    server.use(
      http.get("*/api/", () =>
        HttpResponse.json({ version: "0.11.0", details: null }),
      ),
    );

    expect(await authApi.getVersion()).toEqual({
      version: "0.11.0",
      details: null,
    });
  });
});

describe("registering", () => {
  it("posts the registration data", async () => {
    const seen = stub("post", "/auth/register", { id: "u1" }, 201);
    const data = { email: "a@b.c", password: "pw", full_name: "Ann" };

    await authApi.register(data as Parameters<typeof authApi.register>[0]);

    expect(seen[0]).toMatchObject({
      path: "/api/v1/auth/register",
      body: data,
    });
  });

  it("asks for an account with the name and invite code, so the administrator sees who is asking", async () => {
    const seen = stub("post", "/auth/registration-request", { message: "ok" });
    const request = {
      email: "a@b.c",
      full_name: "Ann",
      invite_code: "X1",
      preferred_language: "pl",
    };

    expect(await authApi.requestRegistration(request)).toEqual({
      message: "ok",
    });
    expect(seen[0].body).toEqual(request);
  });

  it("lists the pending requests across pages", async () => {
    const rows = [{ id: "r1" }];
    stub("get", "/auth/registration-requests", onePage(rows));

    expect(await authApi.getRegistrationRequests()).toEqual(rows);
  });

  it("approves and rejects a request by posting to its own route", async () => {
    const approved = stub("post", "/auth/registration-requests/:id/approve", {
      message: "ok",
      registration_token: "t",
      registration_link: "l",
      email_sent: false,
    });
    const rejected = stub("post", "/auth/registration-requests/:id/reject", {
      message: "no",
    });

    expect(
      (await authApi.approveRegistrationRequest("r1")).registration_token,
    ).toBe("t");
    expect(await authApi.rejectRegistrationRequest("r2")).toEqual({
      message: "no",
    });
    expect(approved[0].path).toBe(
      "/api/v1/auth/registration-requests/r1/approve",
    );
    expect(rejected[0].path).toBe(
      "/api/v1/auth/registration-requests/r2/reject",
    );
  });

  it("encodes the token of an approval link, so a token with a slash still finds its request", async () => {
    let path = "";
    server.use(
      http.get("*/api/v1/auth/registration-link/*", ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json({ email: "a@b.c", full_name: null });
      }),
    );

    expect(await authApi.getRegistrationLink("a/b c")).toEqual({
      email: "a@b.c",
      full_name: null,
    });
    expect(path).toBe("/api/v1/auth/registration-link/a%2Fb%20c");
  });

  it("completes a registration by posting the chosen password and token", async () => {
    const seen = stub("post", "/auth/register-complete", { id: "u1" }, 201);
    const data = { token: "t", password: "pw" };

    await authApi.completeRegistration(
      data as Parameters<typeof authApi.completeRegistration>[0],
    );

    expect(seen[0].body).toEqual(data);
  });
});

describe("the signed-in person's own account", () => {
  it("posts the language to its own route", async () => {
    const seen = stub("post", "/auth/me/language", { id: "u1" });

    await authApi.updateLanguage("de");

    expect(seen[0]).toMatchObject({
      path: "/api/v1/auth/me/language",
      body: { language: "de" },
    });
  });

  it("patches the name or password onto /auth/me", async () => {
    const seen = stub("patch", "/auth/me", { id: "u1" });

    await authApi.updateMe({ full_name: "Ann" });

    expect(seen[0]).toMatchObject({
      method: "PATCH",
      body: { full_name: "Ann" },
    });
  });
});

describe("resetting a password", () => {
  it("returns whether this installation can send mail, so the screen does not promise an email that cannot arrive", async () => {
    const seen = stub("post", "/auth/password-reset/request", {
      status: "accepted",
      email_delivery_configured: false,
    });

    expect(await authApi.requestPasswordReset("a@b.c")).toEqual({
      status: "accepted",
      email_delivery_configured: false,
    });
    expect(seen[0].body).toEqual({ email: "a@b.c" });
  });

  it("confirms with the token and the new password under the snake-case field", async () => {
    const seen = stub("post", "/auth/password-reset/confirm", undefined, 204);

    await authApi.confirmPasswordReset("tok", "new-pw");

    expect(seen[0].body).toEqual({ token: "tok", new_password: "new-pw" });
  });
});
