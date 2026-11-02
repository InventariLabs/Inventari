/**
 * The administration calls reach the routes an administrator's screens expect.
 *
 * A user's block and unblock are the two actions that cannot be told apart
 * by a wrong URL until somebody is locked out (or let back in) by mistake,
 * so the verb, the path and the reason are asserted, not just the call.
 */
import { describe, expect, it } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { rolesApi, uomsApi, usersApi } from "./admin";

interface Seen {
  method: string;
  path: string;
  body: unknown;
}

/** Answers one route and records every request that reached it. */
function stub(
  verb: "get" | "post",
  path: string,
  reply: JsonBodyType = {},
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
      return HttpResponse.json(reply);
    }),
  );
  return seen;
}

describe("usersApi", () => {
  it("reads every user across pages and hands back a plain array", async () => {
    const users = [{ id: "u1" }, { id: "u2" }];
    const seen = stub("get", "/users", onePage(users));

    expect(await usersApi.getAll()).toEqual(users);
    expect(seen[0].path).toBe("/api/v1/users");
  });

  it("reads the organization's members from their own route, not the admin list", async () => {
    const users = [{ id: "u1" }];
    const seen = stub("get", "/users/org-members", onePage(users));

    expect(await usersApi.getOrgMembers()).toEqual(users);
    expect(seen).toHaveLength(1);
  });

  it("activates the named user", async () => {
    const seen = stub("post", "/users/:id/activate", { id: "u1" });

    expect(await usersApi.activate("u1")).toEqual({ id: "u1" });
    expect(seen[0]).toMatchObject({
      method: "POST",
      path: "/api/v1/users/u1/activate",
    });
  });

  it("sends the reason in the body so the server can log why a user was blocked", async () => {
    const seen = stub("post", "/users/:id/block", { id: "u1" });

    await usersApi.block("u1", "left the company");

    expect(seen[0]).toMatchObject({
      path: "/api/v1/users/u1/block",
      body: { reason: "left the company" },
    });
  });

  it("unblocks the named user on the unblock route", async () => {
    const seen = stub("post", "/users/:id/unblock", { id: "u1" });

    expect(await usersApi.unblock("u1")).toEqual({ id: "u1" });
    expect(seen[0].path).toBe("/api/v1/users/u1/unblock");
  });
});

describe("uomsApi", () => {
  it("reads units and their categories from two different routes", async () => {
    const units = [{ id: "kg" }];
    const categories = [{ id: "mass" }];
    stub("get", "/uoms", onePage(units));
    stub("get", "/uoms/categories", onePage(categories));

    expect(await uomsApi.getAll()).toEqual(units);
    expect(await uomsApi.getCategories()).toEqual(categories);
  });
});

describe("rolesApi", () => {
  it("lists the roles and the holders of one role from the role's own route", async () => {
    const roles = [{ id: "r1" }];
    const members = [{ id: "u1" }];
    stub("get", "/roles", onePage(roles));
    const seen = stub("get", "/roles/:id/members", onePage(members));

    expect(await rolesApi.list()).toEqual(roles);
    expect(await rolesApi.members("r1")).toEqual(members);
    expect(seen[0].path).toBe("/api/v1/roles/r1/members");
  });
});
