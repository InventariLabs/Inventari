/**
 * Announcements and the notification bell talk to their own routes.
 *
 * The bell shows the newest page only, so the wrapper must unwrap the
 * envelope to rows; marking one notification read must patch that
 * notification, not read-all.
 */
import { describe, expect, it } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { announcementsApi, notificationsApi } from "./announcements";

interface Seen {
  method: string;
  path: string;
  query: Record<string, string>;
  body: unknown;
}

type Verb = "get" | "post" | "patch" | "delete";

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
        query: Object.fromEntries(url.searchParams),
        body: text ? JSON.parse(text) : undefined,
      });
      return status === 204
        ? new HttpResponse(null, { status })
        : HttpResponse.json(reply, { status });
    }),
  );
  return seen;
}

describe("announcementsApi", () => {
  it("reads the active announcements and all announcements from different routes", async () => {
    const active = [{ id: "a1" }];
    const all = [{ id: "a1" }, { id: "a2" }];
    stub("get", "/announcements/active", onePage(active));
    stub("get", "/announcements", onePage(all));

    expect(await announcementsApi.getActive()).toEqual(active);
    expect(await announcementsApi.getAll()).toEqual(all);
  });

  it("creates an announcement with its title, text and expiry", async () => {
    const seen = stub("post", "/announcements", { id: "a1" }, 201);
    const data = {
      title: "Maintenance",
      content: "Tonight",
      type: "warning",
      active_until: "2026-12-01",
    };

    expect(await announcementsApi.create(data)).toEqual({ id: "a1" });
    expect(seen[0].body).toEqual(data);
  });

  it("deletes an announcement by id", async () => {
    const seen = stub("delete", "/announcements/:id", undefined, 204);

    await announcementsApi.delete("a1");

    expect(seen[0].path).toBe("/api/v1/announcements/a1");
  });
});

describe("notificationsApi", () => {
  it("returns the rows of the newest page and asks for unread only when told", async () => {
    const rows = [{ id: "n1" }];
    const seen = stub("get", "/notifications", onePage(rows));

    expect(await notificationsApi.getAll()).toEqual(rows);
    await notificationsApi.getAll(true);

    expect(seen[0].query).toEqual({ unread_only: "false" });
    expect(seen[1].query).toEqual({ unread_only: "true" });
  });

  it("marks one notification read by patching it with is_read", async () => {
    const seen = stub("patch", "/notifications/:id", { id: "n1" });

    expect(await notificationsApi.markRead("n1")).toEqual({ id: "n1" });
    expect(seen[0]).toMatchObject({
      path: "/api/v1/notifications/n1",
      body: { is_read: true },
    });
  });

  it("marks everything read through the read-all route, not one notification", async () => {
    const seen = stub("post", "/notifications/read-all", { updated: 3 });

    expect(await notificationsApi.markAllRead()).toEqual({ updated: 3 });
    expect(seen[0].path).toBe("/api/v1/notifications/read-all");
  });

  it("deletes one notification and returns the server's answer", async () => {
    const seen = stub("delete", "/notifications/:id", { deleted: true });

    expect(await notificationsApi.delete("n1")).toEqual({ deleted: true });
    expect(seen[0].path).toBe("/api/v1/notifications/n1");
  });
});
