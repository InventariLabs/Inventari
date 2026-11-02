/**
 * The label calls reach the pool and scan routes with the fields they expect.
 *
 * Labels are printed and stuck on boxes, so a mis-sent field is paid for in
 * paper: a preview that marks the pool as printed, a short code that is not
 * encoded and so scans as a different path, an export that drops the ids it
 * was asked for.
 */
import { describe, expect, it } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { labelsApi } from "./labels";

interface Seen {
  method: string;
  path: string;
  search: string;
  body: unknown;
}

type Verb = "get" | "post" | "delete";

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

describe("the label pool", () => {
  it("generates labels from the count and options, returning the new pool rows", async () => {
    const rows = [{ id: "p1" }];
    const seen = stub("post", "/labels/pool/generate", rows, 201);

    expect(await labelsApi.generatePool({ count: 10, prefix: "BOX" })).toEqual(
      rows,
    );
    expect(seen[0].body).toEqual({ count: 10, prefix: "BOX" });
  });

  it("creates labels from codes the user already printed", async () => {
    const seen = stub("post", "/labels/pool/from-codes", [], 201);
    const data = { codes: [{ short_code: "AB12", description: "shelf" }] };

    await labelsApi.createFromCodes(data);

    expect(seen[0]).toMatchObject({
      path: "/api/v1/labels/pool/from-codes",
      body: data,
    });
  });

  it("filters the pool list server-side, so a long pool is not downloaded to be filtered in the browser", async () => {
    const page = { items: [], total: 0 };
    const seen = stub("get", "/labels/pool", page);

    expect(
      await labelsApi.getPool({ unassigned_only: true, limit: 50, offset: 0 }),
    ).toEqual(page);
    expect(new URLSearchParams(seen[0].search).get("unassigned_only")).toBe(
      "true",
    );
    expect(new URLSearchParams(seen[0].search).get("limit")).toBe("50");
  });

  it("deletes a pool label by id", async () => {
    const seen = stub("delete", "/labels/pool/:id", undefined, 204);

    await labelsApi.delete("p1");

    expect(seen[0]).toMatchObject({
      method: "DELETE",
      path: "/api/v1/labels/pool/p1",
    });
  });

  it("reads the pool totals", async () => {
    const stats = { total: 10, assigned: 4, unassigned: 6 };
    stub("get", "/labels/pool/stats", stats);

    expect(await labelsApi.getStats()).toEqual(stats);
  });

  it("unassigns a label by posting to its short code's route", async () => {
    const seen = stub("post", "/labels/pool/:code/unassign", undefined, 204);

    await labelsApi.unassign("AB12");

    expect(seen[0].path).toBe("/api/v1/labels/pool/AB12/unassign");
  });

  it("assigns a label to an existing item with the item id in the query, not the body", async () => {
    const seen = stub("post", "/labels/pool/:code/assign-item", { id: "p1" });

    await labelsApi.assignToExistingItem("AB12", "i1");

    expect(seen[0].path).toBe("/api/v1/labels/pool/AB12/assign-item");
    expect(seen[0].search).toBe("?item_id=i1");
    expect(seen[0].body).toBeNull();
  });
});

describe("scanning a label", () => {
  it("encodes the short code in the path, so a code with reserved characters still reaches its route", async () => {
    const view = { kind: "item" };
    const seen = stub("get", "/labels/scan/*", view);

    expect(await labelsApi.scan("a/b")).toEqual(view);
    expect(seen[0].path).toBe("/api/v1/labels/scan/a%2Fb");
  });

  it("assigns a scanned label by posting the assignment to its route", async () => {
    const seen = stub("post", "/labels/scan/:code/assign", { id: "i1" });
    const data = { name: "Milk", location_id: "l1" } as unknown as Parameters<
      typeof labelsApi.assign
    >[1];

    expect(await labelsApi.assign("AB12", data)).toEqual({ id: "i1" });
    expect(seen[0]).toMatchObject({
      path: "/api/v1/labels/scan/AB12/assign",
      body: data,
    });
  });
});

describe("printing labels", () => {
  it("asks for the file with the default size and count, repeating ids, and returns a blob", async () => {
    let search = "";
    server.use(
      http.get("*/api/v1/labels/pool/export/png", ({ request }) => {
        search = new URL(request.url).search;
        return new HttpResponse("png-bytes", {
          headers: { "Content-Type": "image/png" },
        });
      }),
    );

    const blob = await labelsApi.exportPng({ labelIds: ["a", "b"] });

    const params = new URLSearchParams(search);
    expect(blob).toBeInstanceOf(Blob);
    expect(params.getAll("label_ids")).toEqual(["a", "b"]);
    expect(params.get("count")).toBe("50");
    expect(params.get("width")).toBe("50");
    expect(params.get("height")).toBe("24");
    expect(params.has("mark_printed")).toBe(false);
  });

  it("sends mark_printed=false for a preview, so showing the file does not spend the pool", async () => {
    let search = "";
    server.use(
      http.get("*/api/v1/labels/pool/export/png", ({ request }) => {
        search = new URL(request.url).search;
        return new HttpResponse("png-bytes");
      }),
    );

    await labelsApi.exportPng({
      shortCodes: ["X1"],
      showCode: true,
      qrOnly: false,
      markPrinted: false,
    });

    const params = new URLSearchParams(search);
    expect(params.get("mark_printed")).toBe("false");
    expect(params.get("show_code")).toBe("true");
    expect(params.get("qr_only")).toBe("false");
    expect(params.getAll("short_codes")).toEqual(["X1"]);
  });
});
