/**
 * The partner calls: repeatable type filters, the active switch and the
 * import. A `types` array serialized as `types[]=A` is ignored by the
 * backend, so the filter would silently show every partner.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { api } from "./client";
import { partnersApi } from "./partners";

interface Seen {
  method: string;
  path: string;
  search: string;
}

function stub(
  verb: "get" | "patch",
  path: string,
  reply: JsonBodyType = {},
): Seen[] {
  const seen: Seen[] = [];
  server.use(
    http[verb](`*/api/v1${path}`, ({ request }) => {
      const url = new URL(request.url);
      seen.push({
        method: request.method,
        path: url.pathname,
        search: url.search,
      });
      return HttpResponse.json(reply);
    }),
  );
  return seen;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("partnersApi", () => {
  it("repeats the types parameter, so the backend filters by every type that was picked", async () => {
    const seen = stub("get", "/partners", { items: [], total: 0 });

    await partnersApi.list({ types: ["SUPPLIER", "CUSTOMER"], limit: 10 });

    const params = new URLSearchParams(seen[0].search);
    expect(params.getAll("types")).toEqual(["SUPPLIER", "CUSTOMER"]);
    expect(params.get("limit")).toBe("10");
    expect(seen[0].search).not.toContain("%5B");
  });

  it("deactivates and activates through two different patch routes", async () => {
    const off = stub("patch", "/partners/:id/deactivate", { is_active: false });
    const on = stub("patch", "/partners/:id/activate", { is_active: true });

    expect(await partnersApi.deactivate("p1")).toEqual({ is_active: false });
    expect(await partnersApi.activate("p1")).toEqual({ is_active: true });
    expect(off[0].path).toBe("/api/v1/partners/p1/deactivate");
    expect(on[0].path).toBe("/api/v1/partners/p1/activate");
  });

  it("uploads a sheet for analysis as the file field", async () => {
    const analysis = {
      headers: ["Name"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    };
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: analysis });
    const sheet = new File(["a"], "partners.csv", { type: "text/csv" });

    expect(await partnersApi.analyzeImport(sheet)).toEqual(analysis);
    expect(post.mock.calls[0][0]).toBe("/partners/import/analyze");
    expect((post.mock.calls[0][1] as FormData).get("file")).toBe(sheet);
  });

  it("answers an empty analysis for an oversized sheet and sends nothing", async () => {
    const post = vi.spyOn(api, "post");
    const huge = new File([new Uint8Array(11 * 1024 * 1024)], "p.csv");

    expect(await partnersApi.analyzeImport(huge)).toEqual({
      headers: [],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    expect(post).not.toHaveBeenCalled();
  });

  it("imports with the mapping and the default type that rows without one fall back to", async () => {
    const outcome = { created: 3, errors: [] };
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: outcome });
    const sheet = new File(["a"], "partners.csv", { type: "text/csv" });

    expect(
      await partnersApi.importPartners(sheet, { Name: "name" }, "SUPPLIER"),
    ).toEqual(outcome);

    const form = post.mock.calls[0][1] as FormData;
    expect(post.mock.calls[0][0]).toBe("/partners/import");
    expect(form.get("mapping_json")).toBe(JSON.stringify({ Name: "name" }));
    expect(form.get("default_type")).toBe("SUPPLIER");
  });

  it("refuses to import an oversized sheet", async () => {
    const post = vi.spyOn(api, "post");
    const huge = new File([new Uint8Array(11 * 1024 * 1024)], "p.csv");

    await expect(
      partnersApi.importPartners(huge, {}, "SUPPLIER"),
    ).rejects.toThrow("File too large");
    expect(post).not.toHaveBeenCalled();
  });
});
