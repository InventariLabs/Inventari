import { describe, expect, it } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import {
  homeShelfApi,
  putawayApi,
  putawayCapacityApi,
  receivingModesApi,
} from "./putaway";

interface Seen {
  call: string;
  body: unknown;
}

function record(reply: JsonBodyType = {}) {
  const seen: Seen[] = [];
  server.use(
    http.all("*/api/v1/*", async ({ request }) => {
      const url = new URL(request.url);
      const text = request.method === "GET" ? "" : await request.text();
      seen.push({
        call: `${request.method} ${url.pathname.replace(/^.*\/api\/v1/, "")}`,
        body: text ? JSON.parse(text) : null,
      });
      return HttpResponse.json(reply);
    }),
  );
  return seen;
}

/**
 * The put-away calls are thin; what they can get wrong is the route and the
 * body, and a wrong body here is a rule saved without its target or a
 * warehouse switched to two-step receiving by a request that meant only the
 * free-placement switch.
 */
describe("putaway API — routes and bodies the server reads", () => {
  it("asks the planner for a receipt's lines without saving anything", async () => {
    const seen = record([{ location_id: "loc-2" }]);

    await expect(
      putawayApi.previewReceiptPlan("wh-1", [
        { product_template_id: "pt-1", quantity: "3" } as never,
      ]),
    ).resolves.toEqual([{ location_id: "loc-2" }]);

    expect(seen).toEqual([
      {
        call: "POST /warehouse/putaway/preview",
        body: {
          target_location_id: "wh-1",
          lines: [{ product_template_id: "pt-1", quantity: "3" }],
        },
      },
    ]);
  });

  it("reads, creates, updates and deletes a rule by its id", async () => {
    const seen = record({ id: "rule-1" });

    await putawayApi.getById("rule-1");
    await putawayApi.create({ target_location_id: "loc-1" } as never);
    await putawayApi.update("rule-1", { priority: 2 } as never);
    await putawayApi.delete("rule-1");

    expect(seen).toEqual([
      { call: "GET /warehouse/putaway-rules/rule-1", body: null },
      {
        call: "POST /warehouse/putaway-rules",
        body: { target_location_id: "loc-1" },
      },
      { call: "PUT /warehouse/putaway-rules/rule-1", body: { priority: 2 } },
      { call: "DELETE /warehouse/putaway-rules/rule-1", body: null },
    ]);
  });

  it("changes a capacity limit by sending only the new maximum, and removes one", async () => {
    const seen = record({ id: "cap-1" });

    await putawayCapacityApi.update("cap-1", "12.5");
    await putawayCapacityApi.remove("cap-1");

    expect(seen).toEqual([
      {
        call: "PUT /warehouse/putaway/capacity/cap-1",
        body: { max_quantity: "12.5" },
      },
      { call: "DELETE /warehouse/putaway/capacity/cap-1", body: null },
    ]);
  });

  it("sends only the receiving choices that were made", async () => {
    const seen = record({ warehouse_id: "wh-1" });

    await receivingModesApi.set({ warehouseId: "wh-1", freePlacement: true });
    await receivingModesApi.set({ warehouseId: "wh-1", twoStep: false });

    expect(seen).toEqual([
      {
        call: "PUT /warehouse/putaway/receiving-modes/wh-1",
        body: { free_placement: true },
      },
      {
        call: "PUT /warehouse/putaway/receiving-modes/wh-1",
        body: { two_step: false },
      },
    ]);
  });

  it("asks about a product's home location again by deleting its silence", async () => {
    const seen = record();

    await homeShelfApi.unsilence("pt-9");

    expect(seen).toEqual([
      {
        call: "DELETE /warehouse/putaway/home-shelf/silenced/pt-9",
        body: null,
      },
    ]);
  });
});
