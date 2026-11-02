/**
 * The webhook calls address an endpoint by its id and keep the delivery
 * cursor honest. A first page of deliveries sent with a stale cursor shows
 * the wrong history; a test that goes to the wrong route fires nothing.
 */
import { describe, expect, it } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { webhooksApi } from "./webhooks";

interface Seen {
  method: string;
  path: string;
  query: Record<string, string>;
  body: unknown;
}

type Verb = "get" | "post" | "put" | "delete";

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

describe("webhooksApi", () => {
  it("reads the event catalogue as a plain array", async () => {
    const events = [{ type: "item.created" }];
    stub("get", "/webhooks/events", events);

    expect(await webhooksApi.getAvailableEvents()).toEqual(events);
  });

  it("lists the endpoints across pages and reads one by id", async () => {
    const rows = [{ id: "w1" }];
    stub("get", "/webhooks/endpoints", onePage(rows));
    const one = stub("get", "/webhooks/endpoints/:id", { id: "w1" });

    expect(await webhooksApi.getAll()).toEqual(rows);
    expect(await webhooksApi.getById("w1")).toEqual({ id: "w1" });
    expect(one[0].path).toBe("/api/v1/webhooks/endpoints/w1");
  });

  it("creates an endpoint from the form's fields", async () => {
    const seen = stub("post", "/webhooks/endpoints", { id: "w1" }, 201);
    const data = {
      name: "Hook",
      url: "https://example.com/h",
      event_types: ["item.created"],
      is_active: true,
    };

    expect(
      await webhooksApi.create(
        data as Parameters<typeof webhooksApi.create>[0],
      ),
    ).toEqual({ id: "w1" });
    expect(seen[0].body).toEqual(data);
  });

  it("puts an update on the endpoint's own route", async () => {
    const seen = stub("put", "/webhooks/endpoints/:id", { id: "w1" });

    await webhooksApi.update("w1", { name: "Renamed" });

    expect(seen[0]).toMatchObject({
      method: "PUT",
      path: "/api/v1/webhooks/endpoints/w1",
      body: { name: "Renamed" },
    });
  });

  it("deletes an endpoint by id", async () => {
    const seen = stub("delete", "/webhooks/endpoints/:id", undefined, 204);

    await webhooksApi.delete("w1");

    expect(seen[0].path).toBe("/api/v1/webhooks/endpoints/w1");
  });

  it("fires a test delivery and reactivates through their own post routes", async () => {
    const result = { success: true, status_code: 200 };
    const test = stub("post", "/webhooks/endpoints/:id/test", result);
    const reactivate = stub("post", "/webhooks/endpoints/:id/reactivate", {
      id: "w1",
      is_active: true,
    });

    expect(await webhooksApi.test("w1")).toEqual(result);
    expect(await webhooksApi.reactivate("w1")).toEqual({
      id: "w1",
      is_active: true,
    });
    expect(test[0].path).toBe("/api/v1/webhooks/endpoints/w1/test");
    expect(reactivate[0].path).toBe("/api/v1/webhooks/endpoints/w1/reactivate");
  });

  it("asks for deliveries with a page size of twenty and a cursor only when there is one", async () => {
    const page = { items: [], next_cursor: null };
    const seen = stub("get", "/webhooks/endpoints/:id/deliveries", page);

    expect(await webhooksApi.getDeliveries("w1")).toEqual(page);
    await webhooksApi.getDeliveries("w1", null, 5);
    await webhooksApi.getDeliveries("w1", "c2");

    expect(seen[0].query).toEqual({ limit: "20" });
    expect(seen[1].query).toEqual({ limit: "5" });
    expect(seen[2].query).toEqual({ limit: "20", cursor: "c2" });
  });
});
