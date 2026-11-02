/**
 * Batches are read through one route and held back through another.
 *
 * The status change needs a reason on every call, releases included; a
 * wrapper that sent only the status would come back as a 422 the screen
 * could not explain. The list drops empty filters so "all statuses" is not
 * sent as an empty string the server would reject.
 */
import { describe, expect, it } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { stockLotsApi } from "./stockLots";

interface Seen {
  method: string;
  path: string;
  query: Record<string, string>;
  body: unknown;
}

function stub(
  verb: "get" | "patch",
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

describe("stockLotsApi", () => {
  it("reads one batch by its id", async () => {
    const seen = stub("get", "/stock-lots/:id", { id: "lot1" });

    expect(await stockLotsApi.get("lot1")).toEqual({ id: "lot1" });
    expect(seen[0].path).toBe("/api/v1/stock-lots/lot1");
  });

  it("sends only the filters that have a value, so an unset status is not asked for as an empty string", async () => {
    const page = { items: [], total: 0 };
    const seen = stub("get", "/stock-lots", page);

    expect(
      await stockLotsApi.list({
        product_template_id: "t1",
        status: "" as never,
        limit: 25,
        offset: undefined,
      }),
    ).toEqual(page);
    expect(seen[0].query).toEqual({ product_template_id: "t1", limit: "25" });
  });

  it("lists with no filters when none are given", async () => {
    const seen = stub("get", "/stock-lots", { items: [] });

    await stockLotsApi.list();

    expect(seen[0].query).toEqual({});
  });

  it("patches the status together with the reason, so a hold is never recorded without why", async () => {
    const seen = stub("patch", "/stock-lots/:id", undefined, 204);

    await stockLotsApi.setStatus("lot1", "quarantined", "mould found");

    expect(seen[0]).toMatchObject({
      method: "PATCH",
      path: "/api/v1/stock-lots/lot1",
      body: { status: "quarantined", reason: "mould found" },
    });
  });
});
