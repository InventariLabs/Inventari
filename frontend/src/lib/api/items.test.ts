/**
 * The item calls leave as the backend reads them.
 *
 * Each wrapper is a thin line between a screen and a route, and the ways it
 * goes wrong are all silent: a quantity sent to the wrong verb, a filter
 * dropped before it reaches the query string, a list unwrapped one level
 * too far or too little. The tests run the real client against the mock
 * server and assert what a route would have seen, plus what the caller gets
 * back.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { api } from "./client";
import { ReadableError } from "@/lib/errors";
import { itemsApi } from "./items";

vi.mock("@/lib/imageUtils", () => ({
  prepareImageUpload: vi.fn(async (f: File) => f),
}));

interface Seen {
  method: string;
  path: string;
  query: Record<string, string>;
  body: unknown;
}

type Verb = "get" | "post" | "put" | "patch" | "delete";

/** Answers one route and records every request that reached it. */
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

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("reading items", () => {
  it("passes the list filters through, so a filtered screen is not shown every row", async () => {
    const page = { items: [], total: 0, limit: 10, offset: 20 };
    const seen = stub("get", "/items", page);

    const result = await itemsApi.getAll({
      location_id: "l1",
      only_low_stock: true,
      offset: 20,
      limit: 10,
    });

    expect(result).toEqual(page);
    expect(seen).toHaveLength(1);
    expect(seen[0].query).toEqual({
      location_id: "l1",
      only_low_stock: "true",
      offset: "20",
      limit: "10",
    });
  });

  it("asks the aggregates route with the same filters, so totals match the rows", async () => {
    const totals = { total_items: 3 };
    const seen = stub("get", "/items/aggregates", totals);

    expect(await itemsApi.getAggregates({ search: "milk" })).toEqual(totals);
    expect(seen[0].query).toEqual({ search: "milk" });
  });

  it("sends the module exclusion to the attention counts, so a module's records do not inflate the heading", async () => {
    const counts = { expired: 1, expiring_soon: 2, low_stock: 3 };
    const seen = stub("get", "/items/attention-counts", counts);

    expect(
      await itemsApi.getAttentionCounts({ exclude_module_contexts: true }),
    ).toEqual(counts);
    expect(seen[0].query).toEqual({ exclude_module_contexts: "true" });
  });

  it("unwraps the low-stock rows and asks for a hundred, so the card gets rows and not an envelope", async () => {
    const rows = [{ product_template_id: "p1" }];
    const seen = stub("get", "/stats/low-stock", {
      items: rows,
      total: 1,
      limit: 100,
      offset: 0,
      has_more: false,
    });

    expect(
      await itemsApi.getLowStockProducts({ exclude_module_contexts: true }),
    ).toEqual(rows);
    expect(seen[0].query).toEqual({
      exclude_module_contexts: "true",
      limit: "100",
    });
  });

  it("posts a new item's fields as the body, so nothing is lost on create", async () => {
    const seen = stub("post", "/items", { id: "i1" }, 201);

    const created = await itemsApi.create({
      name: "Milk",
      quantity: 2,
      location_id: "l1",
      unit_confirmed_over_template: false,
    });

    expect(created).toEqual({ id: "i1" });
    expect(seen[0]).toMatchObject({
      method: "POST",
      body: {
        name: "Milk",
        quantity: 2,
        location_id: "l1",
        unit_confirmed_over_template: false,
      },
    });
  });

  it("asks for an archived item only when the caller says so, so live screens never see one", async () => {
    const seen = stub("get", "/items/:id", { id: "i1" });

    await itemsApi.getById("i1");
    await itemsApi.getById("i1", { includeArchived: true });

    expect(seen.map((s) => s.path)).toEqual([
      "/api/v1/items/i1",
      "/api/v1/items/i1",
    ]);
    expect(seen[0].query).toEqual({});
    expect(seen[1].query).toEqual({ include_archived: "true" });
  });

  it("puts an edit on the item's own route, so the right record changes", async () => {
    const seen = stub("put", "/items/:id", { id: "i1", name: "n" });

    const updated = await itemsApi.update("i1", {
      name: "n",
      unit_confirmed_over_template: false,
    });

    expect(updated).toEqual({ id: "i1", name: "n" });
    expect(seen[0]).toMatchObject({
      method: "PUT",
      path: "/api/v1/items/i1",
      body: { name: "n", unit_confirmed_over_template: false },
    });
  });

  it("fetches the recent history and returns only its rows, so the feed gets an array", async () => {
    const rows = [{ id: "h1" }];
    const seen = stub("get", "/items/history", {
      items: rows,
      next_cursor: null,
      has_more: false,
    });

    expect(await itemsApi.getHistory()).toEqual(rows);
    expect(seen[0].query).toEqual({ limit: "20" });
    await itemsApi.getHistory(5);
    expect(seen[1].query).toEqual({ limit: "5" });
  });

  it("returns the whole history page with its cursor, so the next page can be asked for", async () => {
    const page = { items: [{ id: "h1" }], next_cursor: "c2", has_more: true };
    const seen = stub("get", "/items/:id/history", page);

    expect(await itemsApi.getItemHistory("i1", 10, "c1")).toEqual(page);
    expect(seen[0].path).toBe("/api/v1/items/i1/history");
    expect(seen[0].query).toEqual({ limit: "10", cursor: "c1" });

    await itemsApi.getItemHistory("i1");
    expect(seen[1].query).toEqual({ limit: "50" });
  });

  it("searches through the list route and includes emptied records, so a consumed item is still found by name", async () => {
    const rows = [{ id: "i1" }];
    const seen = stub("get", "/items", { items: rows, total: 1 });

    expect(await itemsApi.search("milk")).toEqual(rows);
    expect(seen[0].query).toEqual({
      search: "milk",
      limit: "5",
      include_empty: "true",
    });
  });

  it("resolves a barcode to the product, and to null when the lookup fails, so an unknown code is a miss and not a crash", async () => {
    const found = { name: "Milk" };
    const hit = stub("get", "/items/lookup/:code", found);
    expect(await itemsApi.lookup("590123")).toEqual(found);
    expect(hit[0].path).toBe("/api/v1/items/lookup/590123");

    server.use(
      http.get("*/api/v1/items/lookup/:code", () =>
        HttpResponse.json({ detail: "nope" }, { status: 404 }),
      ),
    );
    expect(await itemsApi.lookup("0")).toBeNull();
  });

  it("passes the archive filters through and returns the page", async () => {
    const page = { items: [], total: 0 };
    const seen = stub("get", "/items/archived", page);

    expect(
      await itemsApi.getArchived({ module_scope: "maker", limit: 25 }),
    ).toEqual(page);
    expect(seen[0].query).toEqual({ module_scope: "maker", limit: "25" });
  });
});

describe("changing stock of an item", () => {
  it("patches the quantity on its own route, so a count does not go through a move", async () => {
    const seen = stub("patch", "/items/:id/quantity", { id: "i1" });

    expect(await itemsApi.updateQuantity("i1", 7)).toEqual({ id: "i1" });
    expect(seen[0]).toMatchObject({
      method: "PATCH",
      path: "/api/v1/items/i1/quantity",
      body: { quantity: 7 },
    });
  });

  it("consumes one unit as USED by default and sends the reason it is given otherwise", async () => {
    const seen = stub("patch", "/items/:id/consume", { id: "i1" });

    await itemsApi.consume("i1");
    await itemsApi.consume("i1", 3, "COOKED", "dinner");

    expect(seen[0].body).toEqual({ quantity: 1, reason: "USED" });
    expect(seen[1].body).toEqual({
      quantity: 3,
      reason: "COOKED",
      notes: "dinner",
    });
  });

  it("discards one unit as DISPOSED by default, so waste is recorded as waste", async () => {
    const seen = stub("patch", "/items/:id/discard", { id: "i1" });

    await itemsApi.discard("i1");
    await itemsApi.discard("i1", 2, "EXPIRED", "mouldy");

    expect(seen[0].body).toEqual({ quantity: 1, reason: "DISPOSED" });
    expect(seen[1].body).toEqual({
      quantity: 2,
      reason: "EXPIRED",
      notes: "mouldy",
    });
  });

  it("opens a package with what is left, so the remainder is not lost", async () => {
    const seen = stub("post", "/items/:id/use-partially", { id: "i1" });

    await itemsApi.openPartly("i1", { left: 0.5, left_uom_id: "u1" });

    expect(seen[0]).toMatchObject({
      method: "POST",
      path: "/api/v1/items/i1/use-partially",
      body: { left: 0.5, left_uom_id: "u1" },
    });
  });

  it("sends a null use-by to clear it, so clearing is not mistaken for leaving it alone", async () => {
    const seen = stub("put", "/items/:id/use-by", { id: "i1" });

    await itemsApi.setUseBy("i1", null);
    await itemsApi.setUseBy("i1", "2026-01-31");

    expect(seen[0].body).toEqual({ use_by: null });
    expect(seen[1].body).toEqual({ use_by: "2026-01-31" });
    expect(seen[0].path).toBe("/api/v1/items/i1/use-by");
  });

  it("moves an item to the named location with the note", async () => {
    const seen = stub("patch", "/items/:id/move", { id: "i1" });

    await itemsApi.move("i1", "loc-2", "shelf full");

    expect(seen[0]).toMatchObject({
      method: "PATCH",
      path: "/api/v1/items/i1/move",
      body: { to_location_id: "loc-2", notes: "shelf full" },
    });
  });

  it("sends the same patch to every selected item in a bulk update and returns the count", async () => {
    const seen = stub("patch", "/items/bulk", { updated: 2 });

    const result = await itemsApi.bulkUpdate({
      item_ids: ["a", "b"],
      update_data: { category_id: "c1", unit_confirmed_over_template: false },
    });

    expect(result).toEqual({ updated: 2 });
    expect(seen[0].body).toEqual({
      item_ids: ["a", "b"],
      update_data: { category_id: "c1", unit_confirmed_over_template: false },
    });
  });
});

describe("removing items", () => {
  it("sends a delete reason as the body only when there is one, so a plain delete stays plain", async () => {
    const seen = stub("delete", "/items/:id", undefined, 204);

    await itemsApi.delete("i1");
    await itemsApi.delete("i2", "DUPLICATE", "entered twice");

    expect(seen[0].body).toBeUndefined();
    expect(seen[1]).toMatchObject({
      path: "/api/v1/items/i2",
      body: { reason: "DUPLICATE", notes: "entered twice" },
    });
  });

  it("restores an archived item by posting to its restore route", async () => {
    const seen = stub("post", "/items/:id/restore", { id: "i1" });

    expect(await itemsApi.restore("i1")).toEqual({ id: "i1" });
    expect(seen[0].path).toBe("/api/v1/items/i1/restore");
  });

  it("purges with the reason in the query, and without one when none is given", async () => {
    const seen = stub("delete", "/items/:id/purge", undefined, 204);

    await itemsApi.purge("i1", "GDPR");
    await itemsApi.purge("i2");

    expect(seen[0].query).toEqual({ reason: "GDPR" });
    expect(seen[1].query).toEqual({});
  });

  it("deletes the picture on the item's image route", async () => {
    const seen = stub("delete", "/items/:id/image", undefined, 204);

    await itemsApi.deleteImage("i1");

    expect(seen[0]).toMatchObject({
      method: "DELETE",
      path: "/api/v1/items/i1/image",
    });
  });
});

describe("files", () => {
  it("exports the rows as a file and passes the filters, so the file matches the screen", async () => {
    let query = "";
    server.use(
      http.get("*/api/v1/items/export/xlsx", ({ request }) => {
        query = new URL(request.url).search;
        return new HttpResponse("sheet-bytes", {
          headers: {
            "Content-Type":
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          },
        });
      }),
    );

    const blob = await itemsApi.exportXlsx({ search: "milk" });

    expect(blob).toBeInstanceOf(Blob);
    expect(blob.size).toBe("sheet-bytes".length);
    expect(query).toBe("?search=milk");
  });

  it("uploads the picture as the image field and returns its url", async () => {
    const post = vi
      .spyOn(api, "post")
      .mockResolvedValue({ data: { image_url: "/img/1.png" } });
    const file = new File(["px"], "a.png", { type: "image/png" });

    const result = await itemsApi.uploadImage("i1", file);

    expect(result).toEqual({ image_url: "/img/1.png" });
    expect(post.mock.calls[0][0]).toBe("/items/i1/image");
    expect((post.mock.calls[0][1] as FormData).get("image")).toBe(file);
  });

  it("refuses a picture above the limit before anything is sent", async () => {
    const post = vi.spyOn(api, "post");
    const big = new File([new Uint8Array(11 * 1024 * 1024)], "big.png", {
      type: "image/png",
    });

    await expect(itemsApi.uploadImage("i1", big)).rejects.toThrow(
      "File too large",
    );
    expect(post).not.toHaveBeenCalled();
  });

  it("uploads a sheet for analysis as the file field", async () => {
    const analysis = {
      headers: ["Name"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    };
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: analysis });
    const sheet = new File(["a"], "items.csv", { type: "text/csv" });

    expect(await itemsApi.analyzeImport(sheet)).toEqual(analysis);
    expect(post.mock.calls[0][0]).toBe("/items/import/analyze");
    expect((post.mock.calls[0][1] as FormData).get("file")).toBe(sheet);
  });

  it("answers an empty analysis for an oversized sheet instead of sending it", async () => {
    const post = vi.spyOn(api, "post");
    const huge = new File([new Uint8Array(11 * 1024 * 1024)], "items.csv");

    expect(await itemsApi.analyzeImport(huge)).toEqual({
      headers: [],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    expect(post).not.toHaveBeenCalled();
  });
});

describe("importing a sheet", () => {
  const sheet = new File(["a"], "items.csv", { type: "text/csv" });
  const outcome = { created: 2, errors: [] };

  it("sends the mapping and both creation flags as separate fields, so one switch cannot grant the other", async () => {
    const post = vi
      .spyOn(api, "post")
      .mockResolvedValue({ status: 200, data: outcome });

    const result = await itemsApi.importItems(
      sheet,
      { Name: "name" },
      false,
      true,
      "skip",
    );

    expect(result).toEqual(outcome);
    const form = post.mock.calls[0][1] as FormData;
    expect(post.mock.calls[0][0]).toBe("/items/import");
    expect(form.get("mapping_json")).toBe(JSON.stringify({ Name: "name" }));
    expect(form.get("create_missing_locations")).toBe("false");
    expect(form.get("create_missing_categories")).toBe("true");
    expect(form.get("on_label_match")).toBe("skip");
  });

  it("creates what is missing and adds on a label match unless told otherwise", async () => {
    const post = vi
      .spyOn(api, "post")
      .mockResolvedValue({ status: 200, data: outcome });

    await itemsApi.importItems(sheet, {});

    const form = post.mock.calls[0][1] as FormData;
    expect(form.get("create_missing_locations")).toBe("true");
    expect(form.get("create_missing_categories")).toBe("true");
    expect(form.get("on_label_match")).toBe("add");
  });

  it("refuses an oversized sheet before sending it", async () => {
    const post = vi.spyOn(api, "post");
    const huge = new File([new Uint8Array(11 * 1024 * 1024)], "items.csv");

    await expect(itemsApi.importItems(huge, {})).rejects.toThrow(
      "File too large",
    );
    expect(post).not.toHaveBeenCalled();
  });

  it("follows a background job until it is done and returns the job's result", async () => {
    vi.useFakeTimers();
    vi.spyOn(api, "post").mockResolvedValue({
      status: 202,
      data: { id: "job-1" },
    });
    const get = vi
      .spyOn(api, "get")
      .mockResolvedValueOnce({ data: { status: "running" } })
      .mockResolvedValueOnce({ data: { status: "done", result: outcome } });

    const pending = itemsApi.importItems(sheet, {});
    await vi.advanceTimersByTimeAsync(1500);

    expect(await pending).toEqual(outcome);
    expect(get).toHaveBeenCalledTimes(2);
    expect(get.mock.calls[0][0]).toBe("/items/import/jobs/job-1");
  });

  it("raises the job's own error when the background import fails", async () => {
    vi.spyOn(api, "post").mockResolvedValue({
      status: 202,
      data: { id: "job-2" },
    });
    vi.spyOn(api, "get").mockResolvedValue({
      data: { status: "failed", error: "bad header row" },
    });

    await expect(itemsApi.importItems(sheet, {})).rejects.toThrow(
      "bad header row",
    );
  });

  it("tells the reader how many rows a failed background import had already saved", async () => {
    vi.spyOn(api, "post").mockResolvedValue({
      status: 202,
      data: { id: "job-3" },
    });
    vi.spyOn(api, "get").mockResolvedValue({
      data: {
        status: "failed",
        error: "The import was interrupted before it finished.",
        processed: 400,
        total: 1000,
      },
    });

    const failure: unknown = await itemsApi
      .importItems(sheet, {})
      .catch((e: unknown) => e);

    expect(failure).toBeInstanceOf(ReadableError);
    expect((failure as Error).message).toContain(
      "The import was interrupted before it finished.",
    );
    // rows the job got through, not rows it imported: failed rows are in it
    expect((failure as Error).message).toMatch(/rows processed/i);
    expect((failure as Error).message).toContain("400");
    expect((failure as Error).message).toContain("1000");
  });

  it("says nothing was imported when a failed background import saved no row", async () => {
    vi.spyOn(api, "post").mockResolvedValue({
      status: 202,
      data: { id: "job-4" },
    });
    vi.spyOn(api, "get").mockResolvedValue({
      data: {
        status: "failed",
        error: "bad header row",
        processed: 0,
        total: 9,
      },
    });

    const failure: unknown = await itemsApi
      .importItems(sheet, {})
      .catch((e: unknown) => e);

    expect((failure as Error).message).toContain("bad header row");
    expect((failure as Error).message).toMatch(/nothing was imported/i);
  });

  it("reports each look at a running background import to the caller", async () => {
    vi.useFakeTimers();
    vi.spyOn(api, "post").mockResolvedValue({
      status: 202,
      data: { id: "job-5" },
    });
    vi.spyOn(api, "get")
      .mockResolvedValueOnce({
        data: { status: "running", processed: 200, total: 900 },
      })
      .mockResolvedValueOnce({ data: { status: "done", result: outcome } });
    const onProgress = vi.fn();

    const pending = itemsApi.importItems(
      sheet,
      {},
      true,
      true,
      "add",
      onProgress,
    );
    await vi.advanceTimersByTimeAsync(1500);
    await pending;

    expect(onProgress).toHaveBeenCalledWith({ processed: 200, total: 900 });
  });
});
