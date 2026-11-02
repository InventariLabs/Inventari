/**
 * The organization calls: settings, logo, invitations and membership.
 *
 * Membership calls change who may do what, so the verb, the path and the
 * role payload are asserted. A custom role travels as `role_id` and a
 * built-in level as `role`, never both: the backend refuses both and
 * neither.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { api } from "./client";
import { organizationsApi } from "./organizations";

vi.mock("@/lib/imageUtils", () => ({
  prepareImageUpload: vi.fn(async (f: File) => f),
}));

interface Seen {
  method: string;
  path: string;
  search: string;
  body: unknown;
}

type Verb = "get" | "post" | "put" | "patch" | "delete";

function stub(
  verb: Verb,
  path: string,
  reply: JsonBodyType = {},
  status = 200,
): Seen[] {
  const seen: Seen[] = [];
  server.use(
    http[verb](`*/api/v1${path}`, async ({ request }) => {
      const url = new URL(request.url);
      const text = await request.text();
      seen.push({
        method: request.method,
        path: url.pathname,
        search: url.search,
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
});

describe("the organization itself", () => {
  it("lists every organization and reads the caller's own from /my", async () => {
    const orgs = [{ id: "o1" }];
    stub("get", "/organizations/all", onePage(orgs));
    stub("get", "/organizations/my", { id: "o1" });

    expect(await organizationsApi.getAll()).toEqual(orgs);
    expect(await organizationsApi.getMe()).toEqual({ id: "o1" });
  });

  it("puts the changed settings on the organizations route", async () => {
    const seen = stub("put", "/organizations", { id: "o1", currency: "PLN" });

    await organizationsApi.update({ currency: "PLN", country: "PL" });

    expect(seen[0]).toMatchObject({
      method: "PUT",
      body: { currency: "PLN", country: "PL" },
    });
  });

  it("uploads the logo as the image field and returns its url", async () => {
    const post = vi
      .spyOn(api, "post")
      .mockResolvedValue({ data: { logo_url: "/logo.png" } });
    const file = new File(["px"], "logo.png", { type: "image/png" });

    expect(await organizationsApi.uploadLogo(file)).toEqual({
      logo_url: "/logo.png",
    });
    expect(post.mock.calls[0][0]).toBe("/organizations/logo");
    expect((post.mock.calls[0][1] as FormData).get("image")).toBe(file);
  });

  it("deletes the logo on the logo route", async () => {
    const seen = stub("delete", "/organizations/logo", undefined, 204);

    await organizationsApi.deleteLogo();

    expect(seen[0].method).toBe("DELETE");
  });

  it("sends the test mail settings and returns the server's message", async () => {
    const seen = stub("post", "/organizations/my/test-email", {
      message: "sent",
    });
    const smtp = { host: "smtp.example.com", port: 587 };

    expect(await organizationsApi.testEmail(smtp)).toEqual({ message: "sent" });
    expect(seen[0].body).toEqual(smtp);
  });
});

describe("invitations", () => {
  it("issues a code for a built-in level with the role and the address", async () => {
    const seen = stub("post", "/organizations/my/invitation-code", {
      code: "X",
    });

    await organizationsApi.createInvitationCode({
      role: "member",
      email: "a@b.c",
    } as Parameters<typeof organizationsApi.createInvitationCode>[0]);

    expect(seen[0].body).toEqual({ role: "member", email: "a@b.c" });
  });

  it("issues a code for a custom role as role_id and not as role", async () => {
    const seen = stub("post", "/organizations/my/invitation-code", {
      code: "X",
    });

    await organizationsApi.createInvitationCode({
      roleId: "r1",
      email: "a@b.c",
    } as Parameters<typeof organizationsApi.createInvitationCode>[0]);

    expect(seen[0].body).toEqual({ role_id: "r1", email: "a@b.c" });
  });

  it("lists invitations and failed mail, the latter as the page's rows", async () => {
    const invitations = [{ id: "i1" }];
    const failed = [{ id: "f1" }];
    stub("get", "/organizations/my/invitations", onePage(invitations));
    stub("get", "/organizations/my/failed-emails", onePage(failed));

    expect(await organizationsApi.listInvitations()).toEqual(invitations);
    expect(await organizationsApi.listFailedEmails()).toEqual(failed);
  });

  it("resends and revokes an invitation by its own id", async () => {
    const resent = stub("post", "/organizations/my/invitations/:id/resend", {
      code: "X",
    });
    const revoked = stub(
      "delete",
      "/organizations/my/invitations/:id",
      undefined,
      204,
    );

    await organizationsApi.resendInvitation("i1");
    await organizationsApi.revokeInvitation("i2");

    expect(resent[0].path).toBe(
      "/api/v1/organizations/my/invitations/i1/resend",
    );
    expect(revoked[0].path).toBe("/api/v1/organizations/my/invitations/i2");
  });

  it("joins with the code in the body", async () => {
    const seen = stub("post", "/organizations/join", { id: "o1" });

    expect(await organizationsApi.join("CODE")).toEqual({ id: "o1" });
    expect(seen[0].body).toEqual({ code: "CODE" });
  });

  it("checks a join link outside the authed API and encodes the code", async () => {
    let path = "";
    server.use(
      http.get("*/public/invitation/*", ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json({ valid: true });
      }),
    );

    expect(await organizationsApi.checkInvitation("a b/c")).toEqual({
      valid: true,
    });
    expect(path).toBe("/public/invitation/a%20b%2Fc");
  });
});

describe("members", () => {
  it("pages the members and adds the search only when there is one", async () => {
    const page = { items: [], total: 0, limit: 20, offset: 0, has_more: false };
    const seen = stub("get", "/organizations/my/members", page);

    expect(await organizationsApi.getMembers()).toEqual(page);
    await organizationsApi.getMembers(40, 10, "ann");

    expect(Object.fromEntries(new URLSearchParams(seen[0].search))).toEqual({
      offset: "0",
      limit: "20",
    });
    expect(Object.fromEntries(new URLSearchParams(seen[1].search))).toEqual({
      offset: "40",
      limit: "10",
      search: "ann",
    });
  });

  it("removes a member by posting to the removal route", async () => {
    const seen = stub(
      "post",
      "/organizations/my/remove-member/:id",
      undefined,
      204,
    );

    await organizationsApi.removeMember("u1");

    expect(seen[0].path).toBe("/api/v1/organizations/my/remove-member/u1");
  });

  it("changes a role by role_id for a custom role and by role for a built-in level, never both", async () => {
    const seen = stub(
      "patch",
      "/organizations/my/members/:id/role",
      undefined,
      204,
    );

    await organizationsApi.changeMemberRole("u1", { roleId: "r1" });
    await organizationsApi.changeMemberRole("u1", { role: "admin" });

    expect(seen[0].body).toEqual({ role_id: "r1" });
    expect(seen[1].body).toEqual({ role: "admin" });
    expect(seen[0].path).toBe("/api/v1/organizations/my/members/u1/role");
  });

  it("leaves the organization with a post and no body", async () => {
    const seen = stub("post", "/organizations/my/leave", undefined, 204);

    await organizationsApi.leave();

    expect(seen[0]).toMatchObject({ method: "POST", body: undefined });
  });
});
